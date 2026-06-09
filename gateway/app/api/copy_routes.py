"""Static-copy bundles served to PDHC consumers — ticket #210.

The patient portal fetches its UI copy from here. Requires authentication
(via :func:`require_auth`) but not a patient-clinic relationship — the
copy is generic UI text, not PHI.

The response always exposes the bundle's ``legal_review_status`` so a
consumer can refuse to render an unapproved bundle on production
surfaces. The portal is expected to gate on
``legal_review_status == "approved"``.
"""
from flask import Blueprint, jsonify, request

from app.services.auth_service import require_auth
from app.services.sparr_copy import loaded as _load_sparr_copy, metadata, section


bp = Blueprint("copy_api", __name__, url_prefix="/api/v1/patient/copy")


@bp.route("/sparr", methods=["GET"])
@require_auth
def get_sparr_copy():
    """Return the full spärr copy bundle (all languages) or, if a
    ``lang`` query string is provided, a flattened bundle in just that
    language.

    Query string:
      lang   optional — "sv" | "en" | …  When omitted, the full
             multi-language bundle is returned.

    Always echoes ``metadata`` at the top level so consumers can see
    the version + legal_review_status without a second call.
    """
    bundle = _load_sparr_copy()
    if not bundle:
        return jsonify({"error": "Copy bundle not available"}), 503

    lang = (request.args.get("lang") or "").strip().lower() or None
    payload = {"metadata": metadata()}

    if lang is None:
        # Return all language variants as-is.
        payload["block_create_confirmation"] = bundle.get(
            "block_create_confirmation", {}
        )
        payload["block_list"] = bundle.get("block_list", {})
        payload["indispensable_care_notification"] = bundle.get(
            "indispensable_care_notification", {}
        )
        payload["common"] = bundle.get("common", {})
    else:
        # Return a single-language slice. Caller can detect language
        # availability via metadata.languages.
        payload["lang"] = lang
        payload["block_create_confirmation"] = section(
            "block_create_confirmation", lang,
        )
        payload["block_list"] = section("block_list", lang)
        payload["indispensable_care_notification"] = section(
            "indispensable_care_notification", lang,
        )
        payload["common"] = section("common", lang)

    return jsonify(payload), 200
