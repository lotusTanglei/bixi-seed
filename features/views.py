from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.services import get_active_membership, user_has_permission, write_audit

from .models import Feature, FeatureRecord
from .services import (
    FEATURE_KEY_RE,
    feature_action_enabled,
    feature_permission_code,
    validate_manifest,
    validate_record_data,
)


def serialize_feature(feature, *, include_manifest=True):
    payload = {
        "id": str(feature.id),
        "key": feature.key,
        "name": feature.name,
        "description": feature.description,
        "status": feature.status,
        "updated_at": feature.updated_at,
    }
    if include_manifest:
        payload["manifest"] = feature.manifest
    return payload


def serialize_record(record):
    return {
        "id": str(record.pk),
        "data": record.data,
        "created_by": record.created_by_id,
        "updated_by": record.updated_by_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def scoped_feature(request, feature_id, *, published_only=False):
    membership = get_active_membership(request)
    if membership is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("当前用户没有组织")
    query = Feature.objects.filter(organization=membership.organization, id=feature_id)
    if published_only:
        query = query.filter(status="published")
    feature = get_object_or_404(query)
    if published_only and validate_manifest(feature.manifest):
        from rest_framework.exceptions import NotFound

        raise NotFound("功能定义不可用")
    return feature


class FeatureListView(APIView):
    def get(self, request):
        membership = get_active_membership(request)
        if membership is None:
            return Response([])
        if not user_has_permission(request, "feature.read"):
            return Response({"detail": "没有查看功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        can_manage = user_has_permission(request, "feature.manage")
        include_unpublished = request.query_params.get("include_unpublished") == "1" and can_manage
        features = Feature.objects.filter(organization=membership.organization)
        if not include_unpublished:
            features = features.filter(status="published")
        return Response(
            [
                serialize_feature(feature)
                for feature in features
                if include_unpublished
                or (not validate_manifest(feature.manifest) and feature_action_enabled(feature, "read"))
            ]
        )

    @transaction.atomic
    def post(self, request):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        membership = get_active_membership(request)
        key = str(request.data.get("key", "")).strip()
        name = str(request.data.get("name", "")).strip()
        manifest = request.data.get("manifest", {})
        errors = validate_manifest(manifest)
        if not key or not name or not FEATURE_KEY_RE.fullmatch(key) or errors:
            return Response({"detail": errors or ["功能参数不完整"]}, status=status.HTTP_400_BAD_REQUEST)
        if Feature.objects.filter(organization=membership.organization, key=key).exists():
            return Response({"detail": "功能编码已存在"}, status=status.HTTP_400_BAD_REQUEST)
        feature = Feature.objects.create(
            organization=membership.organization,
            key=key,
            name=name,
            description=str(request.data.get("description", ""))[:500],
            manifest=manifest,
            created_by=request.user,
        )
        write_audit(
            organization=membership.organization,
            actor=request.user,
            action="feature.created",
            object_type="feature",
            object_id=feature.pk,
            metadata={"key": feature.key, "status": feature.status},
        )
        return Response(serialize_feature(feature), status=status.HTTP_201_CREATED)


class FeatureDetailView(APIView):
    def get(self, request, feature_id):
        feature = scoped_feature(request, feature_id)
        if not feature_action_enabled(feature, "read"):
            return Response({"detail": "该功能不允许查看"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "read")):
            return Response({"detail": "没有查看功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        if feature.status != "published" and not user_has_permission(request, "feature.manage"):
            return Response({"detail": "功能尚未发布"}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_feature(feature))

    @transaction.atomic
    def patch(self, request, feature_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        feature = scoped_feature(request, feature_id)
        if "name" in request.data:
            feature.name = str(request.data["name"]).strip()
        if "description" in request.data:
            feature.description = str(request.data["description"]).strip()[:500]
        if "manifest" in request.data:
            errors = validate_manifest(request.data["manifest"])
            if errors:
                return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
            feature.manifest = request.data["manifest"]
        feature.save()
        write_audit(
            organization=feature.organization,
            actor=request.user,
            action="feature.updated",
            object_type="feature",
            object_id=feature.pk,
            metadata={"changes": list(request.data.keys())},
        )
        return Response(serialize_feature(feature))


class FeatureStateView(APIView):
    state = None

    @transaction.atomic
    def post(self, request, feature_id):
        if not user_has_permission(request, "feature.manage"):
            return Response({"detail": "没有管理功能的权限"}, status=status.HTTP_403_FORBIDDEN)
        feature = scoped_feature(request, feature_id)
        errors = validate_manifest(feature.manifest)
        if self.state == "published" and errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        feature.status = self.state
        feature.save(update_fields=["status", "updated_at"])
        write_audit(
            organization=feature.organization,
            actor=request.user,
            action=f"feature.{self.state}",
            object_type="feature",
            object_id=feature.pk,
            metadata={},
        )
        return Response(serialize_feature(feature))


class FeaturePublishView(FeatureStateView):
    state = "published"


class FeatureDisableView(FeatureStateView):
    state = "disabled"


class FeatureRecordListView(APIView):
    def get_feature(self, request, feature_id):
        feature = scoped_feature(request, feature_id, published_only=True)
        if not feature_action_enabled(feature, "read"):
            return None, Response({"detail": "该功能不允许查看数据"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "read")):
            return None, Response({"detail": "没有查看功能数据的权限"}, status=status.HTTP_403_FORBIDDEN)
        return feature, None

    def get(self, request, feature_id):
        feature, error = self.get_feature(request, feature_id)
        if error:
            return error
        records = list(FeatureRecord.objects.filter(feature=feature).select_related("created_by", "updated_by"))
        search = request.query_params.get("q", "").strip().lower()
        if search:
            search_fields = feature.manifest.get("list", {}).get("search_fields")
            if not search_fields:
                search_fields = [
                    field["key"]
                    for field in feature.manifest.get("fields", [])
                    if field.get("type") in {"text", "enum"}
                ]
            records = [
                record
                for record in records
                if any(search in str(record.data.get(key, "")).lower() for key in search_fields)
            ]
        sort = request.query_params.get("sort", "-updated_at")
        if sort == "created_at":
            records.sort(key=lambda record: record.created_at)
        elif sort == "updated_at":
            records.sort(key=lambda record: record.updated_at)
        elif sort == "-created_at":
            records.sort(key=lambda record: record.created_at, reverse=True)
        elif sort == "-updated_at":
            records.sort(key=lambda record: record.updated_at, reverse=True)
        else:
            descending = sort.startswith("-")
            field_key = sort[1:] if descending else sort
            field_map = {field.get("key"): field for field in feature.manifest.get("fields", [])}
            field = field_map.get(field_key)
            if field is None:
                return Response({"detail": "不支持的排序字段"}, status=status.HTTP_400_BAD_REQUEST)

            def sort_value(record):
                value = record.data.get(field_key)
                if value is None:
                    return (0, 0)
                if field.get("type") == "number":
                    return (1, float(value))
                if field.get("type") == "boolean":
                    return (1, int(bool(value)))
                return (1, str(value).lower())

            records.sort(
                key=sort_value,
                reverse=descending,
            )
        try:
            page = max(int(request.query_params.get("page", "1")), 1)
            page_size = min(max(int(request.query_params.get("page_size", "20")), 1), 100)
        except ValueError:
            return Response({"detail": "page 和 page_size 必须是数字"}, status=status.HTTP_400_BAD_REQUEST)
        start = (page - 1) * page_size
        total = len(records)
        return Response(
            {
                "items": [serialize_record(record) for record in records[start : start + page_size]],
                "pagination": {"page": page, "page_size": page_size, "total": total},
                "feature": serialize_feature(feature),
            }
        )

    @transaction.atomic
    def post(self, request, feature_id):
        feature = scoped_feature(request, feature_id, published_only=True)
        if not feature_action_enabled(feature, "create"):
            return Response({"detail": "该功能不允许创建数据"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "create")):
            return Response({"detail": "没有创建功能数据的权限"}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.get("data", request.data)
        errors = validate_record_data(feature.manifest, data)
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        record = FeatureRecord.objects.create(
            feature=feature,
            data=data,
            created_by=request.user,
            updated_by=request.user,
        )
        write_audit(
            organization=feature.organization,
            actor=request.user,
            action="feature.record.created",
            object_type="feature_record",
            object_id=record.pk,
            metadata={"feature": feature.key},
        )
        return Response(serialize_record(record), status=status.HTTP_201_CREATED)


class FeatureRecordDetailView(APIView):
    def get_record(self, request, feature_id, record_id):
        feature = scoped_feature(request, feature_id, published_only=True)
        return feature, get_object_or_404(FeatureRecord, id=record_id, feature=feature)

    def get(self, request, feature_id, record_id):
        feature, record = self.get_record(request, feature_id, record_id)
        if not feature_action_enabled(feature, "read"):
            return Response({"detail": "该功能不允许查看数据"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "read")):
            return Response({"detail": "没有查看功能数据的权限"}, status=status.HTTP_403_FORBIDDEN)
        return Response(serialize_record(record))

    @transaction.atomic
    def patch(self, request, feature_id, record_id):
        feature, record = self.get_record(request, feature_id, record_id)
        if not feature_action_enabled(feature, "update"):
            return Response({"detail": "该功能不允许修改数据"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "update")):
            return Response({"detail": "没有修改功能数据的权限"}, status=status.HTTP_403_FORBIDDEN)
        patch_data = request.data.get("data", request.data)
        if not isinstance(patch_data, dict):
            return Response({"detail": "data 必须是对象"}, status=status.HTTP_400_BAD_REQUEST)
        data = dict(record.data)
        data.update(patch_data)
        errors = validate_record_data(feature.manifest, data)
        if errors:
            return Response({"detail": errors}, status=status.HTTP_400_BAD_REQUEST)
        record.data = data
        record.updated_by = request.user
        record.save(update_fields=["data", "updated_by", "updated_at"])
        write_audit(
            organization=feature.organization,
            actor=request.user,
            action="feature.record.updated",
            object_type="feature_record",
            object_id=record.pk,
            metadata={"feature": feature.key},
        )
        return Response(serialize_record(record))

    @transaction.atomic
    def delete(self, request, feature_id, record_id):
        feature, record = self.get_record(request, feature_id, record_id)
        if not feature_action_enabled(feature, "delete"):
            return Response({"detail": "该功能不允许删除数据"}, status=status.HTTP_403_FORBIDDEN)
        if not user_has_permission(request, feature_permission_code(feature, "delete")):
            return Response({"detail": "没有删除功能数据的权限"}, status=status.HTTP_403_FORBIDDEN)
        record.delete()
        write_audit(
            organization=feature.organization,
            actor=request.user,
            action="feature.record.deleted",
            object_type="feature_record",
            object_id=record_id,
            metadata={"feature": feature.key},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
