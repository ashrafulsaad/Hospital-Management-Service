import json


def test_openapi_schema_and_swagger_ui_are_available(api):
    schema = api.get(
        "/api/schema/",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )
    assert schema.status_code == 200
    assert json.loads(schema.content)["openapi"].startswith("3.")

    swagger = api.get("/api/docs/")
    assert swagger.status_code == 200
    assert b"SwaggerUIBundle" in swagger.content
