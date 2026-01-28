"""Tests to verify all endpoints are documented in the README.

Uses the pytest subtests pattern to check each endpoint individually.
See: https://til.simonwillison.net/pytest/subtests
"""

from pathlib import Path

from email_server import app


# FastAPI auto-generated routes that don't need documentation
EXCLUDED_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def get_all_endpoints():
    """Extract all API endpoints from the FastAPI app.

    Excludes auto-generated documentation routes.
    """
    endpoints = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            # Skip FastAPI's auto-generated documentation routes
            if route.path in EXCLUDED_PATHS:
                continue
            for method in route.methods:
                # Skip HEAD and OPTIONS which are auto-generated
                if method not in ("HEAD", "OPTIONS"):
                    endpoints.append((method, route.path))
    return endpoints


def test_all_endpoints_documented_in_readme(subtests):
    """Verify each endpoint is documented in the README."""
    readme_path = Path(__file__).parent.parent / "README.md"
    readme_content = readme_path.read_text()

    endpoints = get_all_endpoints()

    for method, path in endpoints:
        with subtests.test(endpoint=f"{method} {path}"):
            # Check for the endpoint header pattern: "### GET /health" or "### POST /search"
            endpoint_header = f"### {method} {path}"
            assert endpoint_header in readme_content, (
                f"Endpoint {method} {path} is not documented in README.md. "
                f"Expected to find '{endpoint_header}'"
            )


def test_readme_has_curl_examples_for_endpoints(subtests):
    """Verify each endpoint has a curl example in the README."""
    readme_path = Path(__file__).parent.parent / "README.md"
    readme_content = readme_path.read_text()

    endpoints = get_all_endpoints()

    for method, path in endpoints:
        with subtests.test(endpoint=f"{method} {path}"):
            # Check for curl example containing the path
            # GET endpoints use: curl http://localhost:8081/path
            # POST endpoints use: curl -X POST http://localhost:8081/path
            if method == "GET":
                curl_pattern = f"curl http://localhost:8081{path}"
            else:
                curl_pattern = f"curl -X {method} http://localhost:8081{path}"

            assert curl_pattern in readme_content, (
                f"Endpoint {method} {path} missing curl example in README.md. "
                f"Expected to find '{curl_pattern}'"
            )


def test_readme_has_response_examples_for_endpoints(subtests):
    """Verify each endpoint has a response example in the README."""
    readme_path = Path(__file__).parent.parent / "README.md"
    readme_content = readme_path.read_text()

    endpoints = get_all_endpoints()

    for method, path in endpoints:
        with subtests.test(endpoint=f"{method} {path}"):
            # Find the section for this endpoint and check it has a Response: block
            endpoint_header = f"### {method} {path}"
            header_pos = readme_content.find(endpoint_header)
            assert header_pos != -1, f"Endpoint section not found for {method} {path}"

            # Find the next section (next ###) or end of file
            next_section = readme_content.find("### ", header_pos + len(endpoint_header))
            if next_section == -1:
                next_section = len(readme_content)

            section_content = readme_content[header_pos:next_section]

            # Check for "Response:" in the section
            assert "Response:" in section_content or "```json" in section_content, (
                f"Endpoint {method} {path} missing response example in README.md"
            )
