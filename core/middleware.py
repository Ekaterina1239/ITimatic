from django.utils import translation


class UserLanguageMiddleware:
    """NFR-02: activate the language saved on the account (or the one picked
    on the login screen). The language never changes on its own."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            code = request.user.language
        else:
            code = request.session.get("lang", "en")
        translation.activate(code)
        request.LANGUAGE_CODE = code
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", code)
        return response
