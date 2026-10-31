from django.urls import path

from .views import (
    FeatureDetailView,
    FeatureDisableView,
    FeatureListView,
    FeaturePublishView,
    FeatureRecordDetailView,
    FeatureRecordListView,
    FeatureRollbackView,
    FeatureVersionDetailView,
    FeatureVersionListView,
)


urlpatterns = [
    path("", FeatureListView.as_view(), name="feature-list"),
    path("<uuid:feature_id>/", FeatureDetailView.as_view(), name="feature-detail"),
    path("<uuid:feature_id>/publish/", FeaturePublishView.as_view(), name="feature-publish"),
    path("<uuid:feature_id>/disable/", FeatureDisableView.as_view(), name="feature-disable"),
    path("<uuid:feature_id>/rollback/", FeatureRollbackView.as_view(), name="feature-rollback"),
    path("<uuid:feature_id>/versions/", FeatureVersionListView.as_view(), name="feature-version-list"),
    path("<uuid:feature_id>/versions/<int:version>/", FeatureVersionDetailView.as_view(), name="feature-version-detail"),
    path("<uuid:feature_id>/records/", FeatureRecordListView.as_view(), name="feature-record-list"),
    path("<uuid:feature_id>/records/<int:record_id>/", FeatureRecordDetailView.as_view(), name="feature-record-detail"),
]
