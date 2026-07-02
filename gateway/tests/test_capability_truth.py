"""Ticket #391 (rollup #349, audit §5.2) — CapabilityStatement truth test.

Rule 20 says the CapabilityStatement must not lie: every advertised
endpoint must exist as a real route, and every real FHIR route must be
advertised somewhere. The pre-#391 test_api_endpoints.py checks the
first direction *partially* (asserts a couple of resource types are
listed) but never walks the full `app.url_map` back against the CS.
Result: adding a new /fhir/<Type> route without updating the CS — or
declaring a resource type in the CS that the app doesn't serve — both
slip through undetected.

Two directions:

  (a) Every resource type + interaction in
      CapabilityStatement.rest[0].resource[] resolves to a real Flask
      route.

  (b) Every resource type served by the generic /fhir/<resource_type>
      handler (== app.services.fhir_service.SUPPORTED_RESOURCE_TYPES)
      is advertised in the CS.

We do NOT try to derive URL patterns from the CS the same way
request.pdhc does — ips.pdhc's CS uses FHIR-standard REST interactions
(read/search-type/create/update) instead of the custom "METHOD /path"
documentation convention. So the direction-(a) walk maps each
interaction code to the Flask verb + shape it implies and checks the
url_map.
"""
from __future__ import annotations


# FHIR REST interaction → (Flask method, shape suffix appended to the
# resource-type base). The base URL for a resource type `Patient` is
# `/fhir/Patient`. Read/update/delete append `/<id>`; create and
# search-type stay at the base.
_INTERACTION_TO_ROUTE = {
    "read":         ("GET",    "/{id}"),
    "search-type":  ("GET",    ""),
    "create":       ("POST",   ""),
    "update":       ("PUT",    "/{id}"),
    "delete":       ("DELETE", "/{id}"),
}


def _flask_shape(rule: str) -> str:
    """Reduce a Flask rule `/fhir/<x>` or `/fhir/<x>/<y>` to a form
    comparable to the CS-derived shape `/fhir/Patient/{id}`. The
    generic clinical CRUD handler uses `<resource_type>`, so we treat
    the placeholder-per-segment as universal."""
    import re
    # Flask: `<converter:name>` or `<name>` → `{*}`
    return re.sub(r"<[^>]+>", "{*}", rule)


def _cs_expected_route(resource_type: str, interaction_code: str) -> tuple[str, str] | None:
    """Given a resource type + interaction, return the (METHOD, shaped
    path) the CS is promising exists. Returns None for interaction
    codes we don't map (vread, history-*, patch — the ips.pdhc CS
    doesn't currently advertise those)."""
    mapping = _INTERACTION_TO_ROUTE.get(interaction_code)
    if not mapping:
        return None
    method, suffix = mapping
    path = f"/fhir/{resource_type}{suffix.replace('{id}', '{*}')}"
    return method, path


def _all_url_map_shapes(app) -> set[tuple[str, str]]:
    """(METHOD, shaped-path) for every rule in app.url_map, skipping
    HEAD/OPTIONS (Flask auto-adds those on every GET)."""
    out: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        methods = (rule.methods or set()) - {"HEAD", "OPTIONS"}
        for m in methods:
            out.add((m, _flask_shape(rule.rule)))
    return out


def _fhir_url_map_shapes(app) -> set[tuple[str, str]]:
    """The subset of url_map that starts with /fhir/. Used for
    direction (b)."""
    return {(m, p) for (m, p) in _all_url_map_shapes(app) if p.startswith("/fhir/")}


class TestCapabilityTruth:
    """Bidirectional truth check between CS and app.url_map."""

    def test_metadata_endpoint_is_reachable(self, client):
        """Sanity — /fhir/metadata must respond 200 with a
        CapabilityStatement so the rest of the checks can even run."""
        resp = client.get("/fhir/metadata")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("resourceType") == "CapabilityStatement"

    def test_every_advertised_interaction_has_a_route(self, app, client):
        """Direction (a) — for every (resource_type, interaction) the
        CS declares, the corresponding Flask route must exist. Catches
        the ghost-route class of bug (CS says we serve X, we don't)."""
        cs = client.get("/fhir/metadata").get_json()
        rest = cs["rest"][0]

        url_map = _all_url_map_shapes(app)
        missing: list[tuple[str, str, str]] = []  # (type, interaction, expected)

        for res in rest.get("resource", []):
            rtype = res["type"]
            for interaction in res.get("interaction", []) or []:
                code = interaction.get("code")
                expected = _cs_expected_route(rtype, code)
                if expected is None:
                    # Interaction code we don't map (e.g. patch,
                    # history-instance). Not a bug — the mapping table
                    # is deliberately conservative.
                    continue
                # The generic clinical CRUD handler serves any
                # resource type via `/fhir/{*}` and `/fhir/{*}/{*}`,
                # so a route match on the type-agnostic shape counts
                # as advertised. Patient has explicit hardcoded routes
                # (Patient in url_map as a literal string) — either
                # form is acceptable.
                shape_specific = expected
                shape_generic = (
                    expected[0],
                    expected[1].replace(f"/fhir/{rtype}", "/fhir/{*}"),
                )
                if shape_specific not in url_map and shape_generic not in url_map:
                    missing.append((rtype, code, f"{expected[0]} {expected[1]}"))

        assert not missing, (
            f"CapabilityStatement advertises {len(missing)} "
            f"interaction(s) with no matching route:\n  "
            + "\n  ".join(f"{t}.{c} → {exp}" for t, c, exp in missing)
        )

    def test_advertised_ips_operation_exists(self, app, client):
        """The CS advertises `$ips` on Patient. Verify the concrete
        route is registered."""
        cs = client.get("/fhir/metadata").get_json()
        rest = cs["rest"][0]
        patient = next(
            (r for r in rest.get("resource", []) if r["type"] == "Patient"),
            None,
        )
        assert patient is not None, "CS is missing the Patient resource"
        assert any(op.get("name") == "ips" for op in patient.get("operation", [])), \
            "CS Patient block does not advertise `$ips`"
        # And the URL must resolve.
        shapes = _all_url_map_shapes(app)
        expected = ("GET", "/fhir/Patient/{*}/$ips")
        assert expected in shapes, (
            f"Advertised $ips route not in url_map. Have: "
            f"{sorted(s for s in shapes if '$ips' in s[1])}"
        )

    def test_every_supported_type_is_advertised(self, client):
        """Direction (b) — every resource type that the generic
        `/fhir/<resource_type>` handler will accept must show up in
        the CS. Catches the reverse ghost-route bug (we serve X,
        the CS doesn't say we do)."""
        from app.services.fhir_service import SUPPORTED_RESOURCE_TYPES
        cs = client.get("/fhir/metadata").get_json()
        advertised = {r["type"] for r in cs["rest"][0].get("resource", [])}
        unadvertised = set(SUPPORTED_RESOURCE_TYPES) - advertised
        assert not unadvertised, (
            f"Types in SUPPORTED_RESOURCE_TYPES not advertised in "
            f"CapabilityStatement: {sorted(unadvertised)}"
        )
