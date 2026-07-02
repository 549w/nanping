"""评价端点测试。

覆盖 GET /review、POST /review/add、DELETE /review/delete、GET /review/me
的正常与异常路径。
"""

import pytest


class TestListReviews:
    """GET /review 测试。"""

    @pytest.mark.asyncio
    async def test_list_reviews(self, client, test_course, test_review):
        """查看课程评价列表应返回评价。"""
        response = await client.get(
            "/review", params={"course_id": test_course.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert data["items"][0]["content"] == "很好的课程"

    @pytest.mark.asyncio
    async def test_list_reviews_pagination(self, client, test_course, test_review):
        """分页参数应正确生效。"""
        response = await client.get(
            "/review",
            params={"course_id": test_course.id, "page": 1, "page_size": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["items"]) <= 5

    @pytest.mark.asyncio
    async def test_list_reviews_excludes_deleted(
        self, client, test_course, test_review, test_review_deleted
    ):
        """已删除评价不应出现在列表中。"""
        response = await client.get(
            "/review", params={"course_id": test_course.id}
        )
        assert response.status_code == 200
        data = response.json()
        contents = [item["content"] for item in data["items"]]
        assert "已删除的评价" not in contents
        assert "很好的课程" in contents

    @pytest.mark.asyncio
    async def test_list_reviews_nonexistent_course(self, client):
        """不存在的课程应返回 404。"""
        response = await client.get("/review", params={"course_id": 99999})
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_reviews_anonymous_email_null(
        self, client, test_course, test_review_anonymous
    ):
        """匿名评价的 user_email 应为 null。"""
        response = await client.get(
            "/review", params={"course_id": test_course.id}
        )
        assert response.status_code == 200
        data = response.json()
        # 找到匿名评价
        anonymous_items = [
            item for item in data["items"] if item["content"] == "匿名好评"
        ]
        assert len(anonymous_items) == 1
        assert anonymous_items[0]["user_email"] is None

    @pytest.mark.asyncio
    async def test_list_reviews_non_anonymous_email_visible(
        self, client, test_course, test_review
    ):
        """非匿名评价应显示用户邮箱。"""
        response = await client.get(
            "/review", params={"course_id": test_course.id}
        )
        assert response.status_code == 200
        data = response.json()
        non_anonymous = [
            item for item in data["items"] if item["content"] == "很好的课程"
        ]
        assert len(non_anonymous) == 1
        assert non_anonymous[0]["user_email"] == "test@nju.edu.cn"


class TestCreateReview:
    """POST /review/add 测试。"""

    @pytest.mark.asyncio
    async def test_create_review_authenticated(
        self, client, test_course, auth_headers
    ):
        """登录用户应能成功提交评价。"""
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": test_course.id,
                "rating": 5,
                "content": "非常棒的课程！",
                "is_anonymous": False,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["content"] == "非常棒的课程！"
        assert data["rating"] == 5
        assert data["user_email"] == "test@nju.edu.cn"

    @pytest.mark.asyncio
    async def test_create_review_unauthenticated(self, client, test_course):
        """未登录提交评价应返回 401。"""
        response = await client.post(
            "/review/add",
            json={
                "course_id": test_course.id,
                "rating": 5,
                "content": "未登录评价",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_review_nonexistent_course(self, client, auth_headers):
        """评价不存在的课程应返回 404。"""
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": 99999,
                "rating": 5,
                "content": "对不存在课程的评价",
            },
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_review_invalid_rating(self, client, test_course, auth_headers):
        """评分超出 1-5 范围应返回 422。"""
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": test_course.id,
                "rating": 6,
                "content": "评分超范围",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_review_anonymous(
        self, client, test_course, auth_headers
    ):
        """匿名评价的 user_email 应为 null。"""
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": test_course.id,
                "rating": 3,
                "content": "匿名评价内容",
                "is_anonymous": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["is_anonymous"] is True
        assert data["user_email"] is None

    @pytest.mark.asyncio
    async def test_create_review_empty_content(self, client, test_course, auth_headers):
        """空评价内容应返回 422。"""
        response = await client.post(
            "/review/add",
            headers=auth_headers,
            json={
                "course_id": test_course.id,
                "rating": 3,
                "content": "",
            },
        )
        assert response.status_code == 422


class TestDeleteReview:
    """DELETE /review/delete 测试。"""

    @pytest.mark.asyncio
    async def test_delete_own_review(self, client, test_review, auth_headers):
        """删除自己的评价应成功。"""
        response = await client.request(
            "DELETE",
            "/review/delete",
            headers=auth_headers,
            json={"review_id": test_review.id},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "删除成功"

    @pytest.mark.asyncio
    async def test_delete_others_review(
        self, client, test_review, auth_headers_user2
    ):
        """删除他人的评价应返回 403。"""
        response = await client.request(
            "DELETE",
            "/review/delete",
            headers=auth_headers_user2,
            json={"review_id": test_review.id},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_already_deleted(
        self, client, test_review_deleted, auth_headers
    ):
        """删除已删除的评价应返回 404。"""
        response = await client.request(
            "DELETE",
            "/review/delete",
            headers=auth_headers,
            json={"review_id": test_review_deleted.id},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_unauthenticated(self, client, test_review):
        """未登录删除评价应返回 401。"""
        response = await client.request(
            "DELETE",
            "/review/delete",
            json={"review_id": test_review.id},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_nonexistent_review(self, client, auth_headers):
        """删除不存在的评价应返回 404。"""
        response = await client.request(
            "DELETE",
            "/review/delete",
            headers=auth_headers,
            json={"review_id": 99999},
        )
        assert response.status_code == 404


class TestMyReviews:
    """GET /review/me 测试。"""

    @pytest.mark.asyncio
    async def test_list_my_reviews(self, client, test_review, auth_headers):
        """查看自己的评价应返回评价列表。"""
        response = await client.get("/review/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        contents = [item["content"] for item in data["items"]]
        assert "很好的课程" in contents

    @pytest.mark.asyncio
    async def test_list_my_reviews_unauthenticated(self, client):
        """未登录查看我的评价应返回 401。"""
        response = await client.get("/review/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_my_reviews_excludes_deleted(
        self, client, test_review, test_review_deleted, auth_headers
    ):
        """我的评价列表不应包含已删除评价。"""
        response = await client.get("/review/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        contents = [item["content"] for item in data["items"]]
        assert "已删除的评价" not in contents

    @pytest.mark.asyncio
    async def test_list_my_reviews_includes_course_info(
        self, client, test_review, test_course, auth_headers
    ):
        """我的评价列表应包含课程信息。"""
        response = await client.get("/review/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        item = data["items"][0]
        assert item["course_name"] is not None
        assert item["course_code"] is not None

    @pytest.mark.asyncio
    async def test_my_reviews_empty_for_new_user(self, client, auth_headers_user2):
        """新用户应返回空列表。"""
        response = await client.get("/review/me", headers=auth_headers_user2)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
