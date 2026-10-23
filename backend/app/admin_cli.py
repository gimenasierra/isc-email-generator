from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from . import server_runtime


def project_report(source: Path, guide: Path | None) -> tuple[dict, dict]:
    project = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(project, dict) or not isinstance(project.get("items", []), list):
        raise ValueError("El archivo no contiene un proyecto válido.")
    clean = json.loads(json.dumps(project))
    excluded = ["credenciales ISC", "API keys de IA", "tokens y sesiones", "estados transitorios de conexión"]
    for connection in clean.get("isc_connections", []):
        connection["status"] = "not_tested"
        connection["status_message"] = "Ingresá nuevamente las credenciales y probá la conexión."
    for item in clean.get("items", []):
        item["publication_preparation"] = None
    guide_content = guide.read_text(encoding="utf-8") if guide and guide.is_file() else ""
    report = {
        "source": str(source.resolve()),
        "project_id": str(clean.get("project_id") or "default"),
        "templates": len(clean.get("items", [])),
        "connections_without_secrets": len(clean.get("isc_connections", [])),
        "adaptations": sum(1 for item in clean.get("items", []) if item.get("result")),
        "publications": sum(len(item.get("publication_history", [])) for item in clean.get("items", [])),
        "style_guide": bool(guide_content),
        "excluded": excluded,
    }
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report["confirmation_hash"] = __import__("hashlib").sha256(canonical.encode("utf-8")).hexdigest()
    return report, {"project": clean, "guide": guide_content, "guide_filename": guide.name if guide else ""}


def migrate(args) -> None:
    source = Path(args.source)
    guide = Path(args.guide) if args.guide else None
    report, content = project_report(source, guide)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.apply:
        print("SIMULACIÓN: no se escribió ningún dato.")
        return
    if args.confirm_hash != report["confirmation_hash"]:
        raise SystemExit("El hash de confirmación no coincide. Ejecutá nuevamente la simulación.")
    server_runtime.initialize()
    with server_runtime.db_session() as db:
        user = db.scalar(__import__("sqlalchemy").select(server_runtime.User).where(server_runtime.User.username == server_runtime.normalize_username(args.username)))
        if not user:
            raise SystemExit("El usuario de destino no existe.")
    token = server_runtime.current_user_id.set(user.id)
    try:
        project_key = report["project_id"]
        existing, version = server_runtime.load_project_state(project_key, {})
        if version and not args.replace:
            raise SystemExit("El proyecto de destino ya existe. No se importó nada; usá --replace solamente después de revisar el respaldo.")
        server_runtime.expected_project_version.set(version)
        server_runtime.save_project_state(project_key, content["project"])
        if content["guide"]:
            server_runtime.save_style_guide_state(project_key, content["guide"], content["guide_filename"] or "guia-estilo.md")
        server_runtime.audit("migration.imported", report, project_key=project_key)
    finally:
        server_runtime.current_user_id.reset(token)
    print("Migración completada sin importar secretos.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Administración del modo servidor")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin")
    create.add_argument("--username", required=True)
    migrate_parser = sub.add_parser("migrate-local")
    migrate_parser.add_argument("--source", required=True)
    migrate_parser.add_argument("--guide")
    migrate_parser.add_argument("--username", required=True)
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.add_argument("--confirm-hash", default="")
    migrate_parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.command == "create-admin":
        server_runtime.initialize()
        password = getpass.getpass("Contraseña temporal (mínimo 12 caracteres): ")
        confirm = getpass.getpass("Repetir contraseña: ")
        if password != confirm:
            raise SystemExit("Las contraseñas no coinciden.")
        print(json.dumps(server_runtime.create_user(args.username, password, "admin", True), ensure_ascii=False))
    else:
        migrate(args)


if __name__ == "__main__":
    main()
