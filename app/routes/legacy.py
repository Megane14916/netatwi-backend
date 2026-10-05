"""Blueprint registration that keeps the existing, unprefixed endpoints."""

from flask import Blueprint


class LegacyEndpointBlueprint(Blueprint):
    def route(self, rule, **options):
        endpoint = options.pop("endpoint", None)

        def decorate(view_func):
            # Blueprint.route normally prefixes the endpoint with its name.
            # Defer the same app.add_url_rule call used before the move so that
            # url_for and the public URL map retain their existing endpoints.
            def register(state):
                state.app.add_url_rule(
                    rule,
                    endpoint=endpoint or view_func.__name__,
                    view_func=view_func,
                    **options,
                )

            self.record(register)
            return view_func

        return decorate
