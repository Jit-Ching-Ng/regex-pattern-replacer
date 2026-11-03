from django.contrib import admin

from processor.models import Dataset, Operation


class OperationInline(admin.TabularInline):
    model = Operation
    extra = 0
    fields = ("sequence", "kind", "instruction", "pattern", "replacement", "created_at")
    readonly_fields = fields
    can_delete = False


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "file_type", "row_count", "size_bytes", "created_at")
    search_fields = ("name",)
    readonly_fields = ("id", "base_snapshot", "base_columns", "created_at", "updated_at")
    inlines = [OperationInline]


@admin.register(Operation)
class OperationAdmin(admin.ModelAdmin):
    list_display = ("dataset", "sequence", "kind", "instruction", "created_at")
    list_filter = ("kind",)
    search_fields = ("instruction", "pattern")
