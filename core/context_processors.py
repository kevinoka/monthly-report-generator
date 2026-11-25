def nav_section(request):
    """Which top-menu item is active, for templates/portal/_header.html."""
    match = getattr(request, "resolver_match", None)
    if not match:
        return {}
    if match.app_name == "core":
        return {"section": "downtime"}
    if match.app_name == "reports":
        return {"section": "generate" if match.url_name == "generate" else "reports"}
    return {}
