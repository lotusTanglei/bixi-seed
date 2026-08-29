from django.db import connection
from django.http import JsonResponse


def health(request):
    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse(
            {"status": "error", "service": "bixi-seed-core"}, status=503
        )
    return JsonResponse(
        {"status": "ok", "service": "bixi-seed-core", "version": "0.1.0"}
    )
