"""使用大模型对未评分的课程评价进行 AI 评分。

查询 Review 表中 rating 为 NULL 且 ai_rated = 0 的记录，
调用 LLM 分析评价内容并给出 1-5 分，写入数据库。

支持所有 OpenAI 兼容的 API（OpenAI / DeepSeek / Qwen / 智谱 / Ollama 等）。

用法：
    cd nanping
    source .venv/bin/activate
    python backend/scripts/ai_rate_reviews.py

环境变量（在 backend/.env 中配置）：
    LLM_API_KEY        必填，API 密钥
    LLM_BASE_URL       默认 https://api.openai.com/v1
    LLM_MODEL          默认 gpt-4o-mini
    LLM_DELAY_SECONDS  调用间隔，默认 0.5 秒
    LLM_MAX_RETRIES    失败重试次数，默认 3
"""

import asyncio
import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import Column, Integer, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# ---------- 配置 ----------

DB_PATH = "data/nanping.db"

# ---------- 评分 Prompt ----------

SYSTEM_PROMPT = """你是一个课程评价评分助手。你的任务是根据学生对大学课程的文字评价，给出一个 1-5 分的综合评分。

评分标准：
- 5 分：强烈推荐。评价充满热情，对课程和教师都高度满意，使用了"强烈推荐""非常好""最棒""宝藏"等强烈正面词汇，或明确表示"一定要选"。
- 4 分：推荐。评价总体正面，对课程或教师有明确肯定（如"老师认真""给分好""能学到东西"），但语气较为平实。
- 3 分：中性 / 好坏参半。评价既有表扬也有批评，或者纯粹是事实描述（如只描述课程内容、考核方式）而不带明显情感倾向。内容过短无法判断也归为此类。
- 2 分：不推荐。评价以负面为主，对课程或教师有明显不满（如"给分低""任务重""学不到东西"），但仍有可取之处。
- 1 分：强烈不推荐。评价充满负面情绪，使用了"差""不要选""浪费时间""快跑"等强烈负面词汇。

评分规则：
1. 重点关注评价的情感倾向和推荐意愿，而非评价长度。
2. 如果评价是纯粹的事实描述（如"这门课讲XXX内容，考核方式是XXX"），评分 3 分。
3. 如果评价提到给分好、任务轻松、老师认真负责等，应偏高。
4. 如果评价提到给分差、任务繁重、老师敷衍等，应偏低。
5. 如果评价内容过短或无法判断（如只有"还行""一般""水课"），评分 3 分。

你必须回复且只回复一个 1-5 之间的整数，务必不要回复其他任何内容。"""

USER_PROMPT_TEMPLATE = "请为这条课程评价打分（只需回复一个 1-5 的整数）：\n\n{content}"

# ---------- 独立模型 ----------


class Base(DeclarativeBase):
    pass


class Review(Base):
    __tablename__ = "review"
    id = Column(Integer, primary_key=True, autoincrement=True)
    course_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    rating = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    semester = Column(Text, nullable=True)
    is_anonymous = Column(Integer, nullable=False, default=0)
    is_deleted = Column(Integer, nullable=False, default=0)
    source = Column(Text, nullable=False, default="native")
    ai_rated = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False)


# ---------- 数据库 ----------

engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _ensure_ai_rated_column():
    """确保 review 表存在 ai_rated 列（兼容旧数据库）。"""
    import sqlalchemy as sa

    async with engine.begin() as conn:
        result = await conn.execute(sa.text("PRAGMA table_info(review)"))
        columns = [row[1] for row in result.fetchall()]
        if "ai_rated" not in columns:
            print("[迁移] 添加 review.ai_rated 列...")
            await conn.execute(
                sa.text("ALTER TABLE review ADD COLUMN ai_rated INTEGER DEFAULT 0")
            )
            print("[迁移] 完成。")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- 配置加载 ----------


def _load_config() -> dict:
    """从 .env 加载 LLM API 配置。"""
    load_dotenv()

    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    delay_seconds = float(os.getenv("LLM_DELAY_SECONDS", "0.5"))
    max_retries = int(os.getenv("LLM_MAX_RETRIES", "3"))

    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY 未在 .env 中设置。\n"
            "请在 backend/.env 中添加：LLM_API_KEY=你的API密钥"
        )

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model_name,
        "delay_seconds": delay_seconds,
        "max_retries": max_retries,
    }


def _tokens_str(prompt: int, completion: int, cached: int = 0) -> str:
    """格式化 token 用量字符串。"""
    parts = [f"p={prompt}", f"c={completion}"]
    if cached > 0:
        parts.append(f"cache={cached}")
    return f"tokens({' '.join(parts)})"


# ---------- 核心逻辑 ----------


def _extract_cached_tokens(usage) -> int:
    """安全提取缓存命中 token 数，兼容不同 API 返回格式。"""
    try:
        details = usage.prompt_tokens_details
        if details is not None:
            return getattr(details, "cached_tokens", 0) or 0
    except Exception:
        pass
    return 0


async def rate_review(
    client: AsyncOpenAI,
    model: str,
    content: str,
    max_retries: int = 3,
) -> tuple[int | None, int, int, int]:
    """调用 LLM 对单条评价评分。

    Args:
        client: AsyncOpenAI 客户端。
        model: 模型名称。
        content: 评价正文。
        max_retries: 最大重试次数。

    Returns:
        (rating, prompt_tokens, completion_tokens, cached_tokens)
        rating 为 None 表示评分失败。
    """
    content = content.strip()

    # 内容过短直接返回 3 分，不消耗 API 调用
    if len(content) < 4:
        return 3, 0, 0, 0

    user_message = USER_PROMPT_TEMPLATE.format(content=content)

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=10,
            )

            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            cached_tokens = _extract_cached_tokens(usage) if usage else 0

            message = response.choices[0].message
            raw = (message.content or "").strip()

            # DeepSeek R1 等推理模型输出在 reasoning_content，content 可能为空
            if not raw:
                reasoning = getattr(message, "reasoning_content", None)
                if reasoning:
                    raw = (reasoning or "").strip()

            if not raw:
                print(f"  [WARN] API 返回空内容（模型可能是推理模型？尝试用 deepseek-chat 而非 deepseek-reasoner）")
                return None, prompt_tokens, completion_tokens, cached_tokens

            match = re.search(r"[1-5]", raw)
            if match:
                rating = int(match.group(0))
                return rating, prompt_tokens, completion_tokens, cached_tokens

            # LLM 返回了内容但没有有效数字
            print(f"  [WARN] 无法从回复中提取评分: \"{raw[:80]}\"")
            return None, prompt_tokens, completion_tokens, cached_tokens

        except Exception as e:
            print(f"  [ERROR] API 调用失败 (第 {attempt + 1}/{max_retries} 次): {e}")
            if attempt < max_retries - 1:
                wait = 2**attempt
                await asyncio.sleep(wait)
            else:
                return None, 0, 0, 0


async def main():
    await _ensure_ai_rated_column()

    config = _load_config()

    print("=" * 60)
    print("Nanping AI 评分脚本")
    print(f"  模型:     {config['model']}")
    print(f"  API:      {config['base_url']}")
    print(f"  调用间隔: {config['delay_seconds']}s")
    print(f"  最大重试: {config['max_retries']} 次")
    print("=" * 60)
    print()

    client = AsyncOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
    )

    async with async_session() as session:
        result = await session.execute(
            select(Review).where(
                Review.rating.is_(None),
                Review.ai_rated == 0,
                Review.is_deleted == 0,
            )
        )
        reviews = result.scalars().all()

    print(f"待评分评价: {len(reviews)} 条\n")

    if not reviews:
        print("没有需要评分的评价。")
        return

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cached_tokens = 0
    rated_count = 0
    failed_count = 0
    skipped_short = 0

    for i, review in enumerate(reviews, 1):
        rating, prompt_tok, comp_tok, cached_tok = await rate_review(
            client, config["model"], review.content, config["max_retries"]
        )

        total_prompt_tokens += prompt_tok
        total_completion_tokens += comp_tok
        total_cached_tokens += cached_tok

        # 内容预览（截断到 50 字符，替换换行）
        preview = review.content[:50].replace("\n", " ")
        if len(review.content) > 50:
            preview += "..."

        if rating is not None:
            async with async_session() as session:
                r = await session.get(Review, review.id)
                r.rating = rating
                r.ai_rated = 1
                await session.commit()

            rated_count += 1
            print(
                f"[{i}/{len(reviews)}] ID={review.id:>5} | "
                f"评分={rating} | "
                f"{_tokens_str(prompt_tok, comp_tok, cached_tok)} | "
                f"\"{preview}\""
            )
        else:
            failed_count += 1
            if prompt_tok == 0 and comp_tok == 0:
                skipped_short += 1
            print(
                f"[{i}/{len(reviews)}] ID={review.id:>5} | "
                f"FAILED | "
                f"\"{preview}\""
            )

        # 调用间隔
        if i < len(reviews):
            await asyncio.sleep(config["delay_seconds"])

    # ---- 最终报告 ----
    total_all = total_prompt_tokens + total_completion_tokens
    print()
    print("=" * 60)
    print("评分完成！")
    print(f"  总计:               {len(reviews):>6} 条")
    print(f"  成功:               {rated_count:>6} 条")
    print(f"  失败:               {failed_count:>6} 条")
    if skipped_short > 0:
        print(f"    (其中 {skipped_short} 条因内容过短自动给 3 分)")
    print(f"  累计 prompt tokens:     {total_prompt_tokens:>10}")
    print(f"  累计 completion tokens: {total_completion_tokens:>10}")
    if total_cached_tokens > 0:
        print(f"  累计 cache hit tokens:  {total_cached_tokens:>10}")
    print(f"  累计 total tokens:      {total_all:>10}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已中断。已评分的评价已保存到数据库。")
    except RuntimeError as e:
        print(f"\n配置错误: {e}")
