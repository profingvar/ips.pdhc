"""API key management and auth routes."""

import secrets
import hashlib

from flask import Blueprint, jsonify, request, g

from app.models.base import db, utcnow
from app.models.api_key import ApiKey
from app.services.auth_service import require_auth, hash_api_key
from app.services.audit_service import log_event

bp = Blueprint("auth_api", __name__, url_prefix="/api/v1/auth")


@bp.route("/keys", methods=["POST"])
@require_auth
def create_key():
    """Create a new API key. The plaintext is returned exactly once."""
    data = request.get_json(silent=True) or {}

    raw_key = secrets.token_urlsafe(48)
    prefix = raw_key[:8]
    key_hash = hash_api_key(raw_key)

    api_key = ApiKey(
        user_guid=getattr(g.current_user, "guid", None),
        key_hash=key_hash,
        label=data.get("label", ""),
        prefix=prefix,
        scopes=data.get("scopes", []),
        expires_at=data.get("expires_at"),
    )
    db.session.add(api_key)
    log_event("api_key_create", resource_guid=api_key.guid)
    db.session.commit()

    result = api_key.to_dict()
    result["key"] = raw_key  # Shown once only
    return jsonify(result), 201


@bp.route("/keys", methods=["GET"])
@require_auth
def list_keys():
    """List API keys (prefix and metadata only — never the hash)."""
    keys = db.session.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return jsonify([k.to_dict() for k in keys])


@bp.route("/keys/<guid>", methods=["DELETE"])
@require_auth
def revoke_key(guid):
    """Revoke an API key immediately."""
    api_key = db.session.query(ApiKey).filter_by(guid=guid).first()
    if not api_key:
        return jsonify({"error": "API key not found"}), 404

    api_key.is_active = False
    api_key.revoked_at = utcnow()
    log_event("api_key_revoke", resource_guid=api_key.guid)
    db.session.commit()
    return jsonify(api_key.to_dict())


@bp.route("/keys/<guid>/rotate", methods=["POST"])
@require_auth
def rotate_key(guid):
    """Rotate: revoke old key, issue new one."""
    old_key = db.session.query(ApiKey).filter_by(guid=guid).first()
    if not old_key:
        return jsonify({"error": "API key not found"}), 404

    # Revoke old
    old_key.is_active = False
    old_key.revoked_at = utcnow()
    log_event("api_key_revoke", resource_guid=old_key.guid, detail={"reason": "rotation"})

    # Create new
    raw_key = secrets.token_urlsafe(48)
    prefix = raw_key[:8]
    key_hash = hash_api_key(raw_key)

    new_key = ApiKey(
        user_guid=old_key.user_guid,
        key_hash=key_hash,
        label=old_key.label,
        prefix=prefix,
        scopes=old_key.scopes,
        expires_at=old_key.expires_at,
    )
    db.session.add(new_key)
    log_event("api_key_create", resource_guid=new_key.guid, detail={"rotated_from": str(old_key.guid)})
    db.session.commit()

    result = new_key.to_dict()
    result["key"] = raw_key
    return jsonify(result), 201
