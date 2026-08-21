"""缓存失效回归测试。

回归背景：插件 /plugin 端点会缓存 30 秒的 top_reviews。
如果 /review/add 和 /review/delete 不主动失效缓存，
用户提交/删除评价后立即刷新插件会看不到变更（旧数据被缓存）。
本测试保证未来任何对缓存的改动都不会让这个 bug 重新出现。
"""

import pytest


class TestCacheInvalidation:
    """/review 写操作必须让 /plugin 缓存立即失效。"""

    @pytest.mark.asyncio
    async def test_create_review_invalidates_plugin_cache(
        self, client, auth_headers, test_user, test_course, test_offering, test_review
    ):
        """提交新评价后，/plugin 立即返回新评价（无 30 秒延迟）。"""
        # 1. 先让 /plugin 预热缓存（让数据进缓存）
        warmup = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": test_course.code, "teacher": test_course.teacher, "name": test_course.name}
                ]
            },
        )
        assert warmup.status_code == 200
        # 确认 warmup 后没新评价内容
        warmup_html = warmup.json()["courses"][0]["panel_html"]
        assert "全新的评价内容" not in warmup_html

        # 2. 提交新评价
        new_content = "全新的评价内容" + "_" + "x" * 20  # 足够独特，不会误中
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": test_course.id,
                "rating": 5,
                "content": new_content,
                "semester": "2025春",
                "is_anonymous": False,
            },
        )
        assert response.status_code == 201

        # 3. 立即重新查询 /plugin，新评价应立刻可见（无延迟）
        result = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": test_course.code, "teacher": test_course.teacher, "name": test_course.name}
                ]
            },
        )
        assert result.status_code == 200
        panel_html = result.json()["courses"][0]["panel_html"]
        assert new_content in panel_html, (
            "缓存未失效：提交评价 30 秒后还在返回旧评价"
        )

    @pytest.mark.asyncio
    async def test_delete_review_invalidates_plugin_cache(
        self, client, auth_headers, test_user, test_course, test_offering, test_review
    ):
        """删除评价后，/plugin 立即不再返回该评价。"""
        # 1. 先让 /plugin 预热缓存
        warmup = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": test_course.code, "teacher": test_course.teacher, "name": test_course.name}
                ]
            },
        )
        assert warmup.status_code == 200
        # 确认 warmup 后有这条评价
        warmup_html = warmup.json()["courses"][0]["panel_html"]
        assert test_review.content in warmup_html

        # 2. 软删除评价
        response = await client.request(
            "DELETE",
            "/review/delete",
            headers=auth_headers,
            json={"review_id": test_review.id},
        )
        assert response.status_code == 200

        # 3. 立即重新查询 /plugin，被删评价应立刻消失
        result = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": test_course.code, "teacher": test_course.teacher, "name": test_course.name}
                ]
            },
        )
        assert result.status_code == 200
        panel_html = result.json()["courses"][0]["panel_html"]
        assert test_review.content not in panel_html, (
            "缓存未失效：删除评价 30 秒后还在返回已删评价"
        )
