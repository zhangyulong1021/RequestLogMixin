import json
from deepdiff import DeepDiff
from django.db.models import QuerySet
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from autobutler_open.apps.account.models.user import User

from autobutler_open.common.db.models import BaseModel
from rest_framework.response import Response

from autobutler_open.common.serializers import JSONEncoder
from custom_logger import logger

class OperateLogMixin:
    """记录用户对接口操作日志"""

    @classmethod
    def as_view(cls, *args, **kwargs):
        view = super().as_view(*args, **kwargs)
        view = cls.decorator(view)
        return csrf_exempt(view)

    @classmethod
    def method_conf(cls):
        """
        各动作是否需要返回 model 序列化处理之前、之后的结果
        key = action
        value:tuple = (before: bool, after: bool)
        """
        return {
            "get": (False, False),
            "post": (False, True),
            "put": (True, True),
            "patch": (True, True),
            "delete": (True, False),
        }

    @staticmethod
    def add_log(**kwargs):
        row = {
            "version": "1.0",
            "url": kwargs.get("path"),
            "method": kwargs.get("method"),
            "body": kwargs.get("body"),
            "response": kwargs.get("response"),
            "headers": kwargs.get("header"),
            "before": kwargs.get("before"),
            "after": kwargs.get("after"),
            "diff": kwargs.get("diff"),
            "operator_id": kwargs.get("operator_id"),
            "is_manager": kwargs.get("is_manager"),
            "create_time": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logger.info(json.dumps(row, ensure_ascii=False, cls=JSONEncoder))

    @classmethod
    def get_serializer_data(cls, request, queryset, serializer_class, **kwargs):
        try:
            model: BaseModel = queryset.model.objects.get(**kwargs)
        except queryset.model.DoesNotExist:
            return None
        return serializer_class(model, context={"request": request}).data

    @classmethod
    def get_resp_data(cls, resp):
        if isinstance(resp, Response):
            return resp.data
        if isinstance(resp, (JsonResponse, HttpResponse)):
            content = getattr(resp, "content", None)
            if not content:
                return dict()
            return json.loads(content.decode() or "{}")
        return dict()

    @classmethod
    def deal_arguments(
        cls, request, req_data, resp, before=None, after=None
    ):  # pylint: disable=too-many-arguments

        if not after:
            diff = None
        elif not before and after:
            diff = after
        else:
            diff = DeepDiff(
                before,
                after,
                exclude_paths={"root['create_time']", "root['update_time']"},
            ).to_json()
            # 因存在 type change 情况，自定义JSONEncoder无法正确encode情况，让其使用内置encoder序列化
            diff = json.loads(diff)
        kwargs = {
            "path": request.path,
            "method": request.method,
            "body": req_data,
            "response": cls.get_resp_data(resp),
            "headers": dict(request.headers),
            "before": before,
            "after": after,
            "diff": diff,
            "operator_id": str(request.user.id),
            "is_manager": isinstance(request.user, User),
        }
        # 进行日志记录
        cls.add_log(**kwargs)

    @classmethod
    def decorator(cls, func):
        def wrapper(request, *args, **kwargs):
            before_object = after_object = None
            req_data = json.loads(request.body.decode()) if request.body else {}
            # 获取各参数
            serializer_class = getattr(func.cls, "serializer_class", None)
            queryset = getattr(func.cls, "queryset", None)
            if not all([serializer_class and isinstance(queryset, QuerySet)]):
                resp = func(request, *args, **kwargs)
                cls.deal_arguments(request, req_data, resp)
                return resp

            action = request.method.lower()
            lookup_url_kwarg = func.cls.lookup_url_kwarg or func.cls.lookup_field
            lookup = {func.cls.lookup_field: kwargs.get(lookup_url_kwarg)}
            before, after = cls.method_conf().get(action, (False, False))
            if before:
                before_object = cls.get_serializer_data(
                    request, queryset, serializer_class, **lookup
                )
            resp = func(request, *args, **kwargs)
            if after:
                after_object = cls.get_serializer_data(
                    request, queryset, serializer_class, **lookup
                )
            cls.deal_arguments(request, req_data, resp, before_object, after_object)
            return resp

        return wrapper
