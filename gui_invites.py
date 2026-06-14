from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import re
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "json"
PROJECTS_DIR = DATA_DIR / "projects"
ACTIVE_PROJECT_PATH = DATA_DIR / "active_project.txt"
LEGACY_INVITES_PATH = DATA_DIR / "Liste_Inviter.json"
HTML_PATH = BASE_DIR / "invites_gui.html"
MESSAGE_PATH = BASE_DIR / "MessagePublier"


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_money(value, default=0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "party"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PROJECTS_DIR.mkdir(exist_ok=True)


def invite_label(invite: dict) -> str:
    groupe = str(invite.get("groupe") or "").strip()
    if groupe:
        return groupe

    personnes = invite.get("personnes")
    if isinstance(personnes, list) and personnes:
        return ", ".join(str(personne) for personne in personnes)

    return "Invite sans nom"


def guest_count_text(invite: dict) -> str:
    nombre_min = normalize_int(invite.get("nombre_min"), 0)
    nombre_max = normalize_int(invite.get("nombre_max"), nombre_min)
    if nombre_min == nombre_max:
        return f"{nombre_max} personne" if nombre_max <= 1 else f"{nombre_max} personnes"
    return f"{nombre_min} a {nombre_max} personnes"


def recalculate_invites(project: dict) -> dict:
    invites = project.get("invites")
    if not isinstance(invites, list):
        invites = []
        project["invites"] = invites

    total_min = 0
    total_max = 0
    presents = 0
    absents = 0
    peut_etre = 0
    presence_inconnue = 0
    a_confirmer = []

    for invite in invites:
        if not isinstance(invite, dict):
            continue

        invite["groupe"] = str(invite.get("groupe") or "").strip()
        personnes = invite.get("personnes")
        invite["personnes"] = personnes if isinstance(personnes, list) else []
        invite["statut"] = str(invite.get("statut") or "a_inviter").strip()
        invite["presence"] = str(invite.get("presence") or "inconnue").strip()
        invite["notes"] = str(invite.get("notes") or "")

        nombre_min = normalize_int(invite.get("nombre_min"), 0)
        nombre_max = normalize_int(invite.get("nombre_max"), nombre_min)
        if nombre_max < nombre_min:
            nombre_max = nombre_min

        invite["nombre_min"] = nombre_min
        invite["nombre_max"] = nombre_max
        total_min += nombre_min
        total_max += nombre_max

        if invite["statut"] == "a_confirmer" or nombre_min < nombre_max:
            a_confirmer.append(invite_label(invite))

        if invite["presence"] == "present":
            presents += nombre_max
        elif invite["presence"] == "absent":
            absents += nombre_max
        elif invite["presence"] == "peut_etre":
            peut_etre += nombre_max
        else:
            presence_inconnue += nombre_max

    project["resume"] = {
        **(project.get("resume") if isinstance(project.get("resume"), dict) else {}),
        "nombre_minimum": total_min,
        "nombre_maximum": total_max,
        "presence_confirmee": presents,
        "presence_absente": absents,
        "presence_peut_etre": peut_etre,
        "presence_inconnue": presence_inconnue,
        "a_confirmer": a_confirmer,
    }
    return project


def normalize_preparation(project: dict) -> dict:
    preparation = project.get("preparation")
    if not isinstance(preparation, dict):
        preparation = {}

    for section in ("restaurant", "maison"):
        items = preparation.get(section)
        if not isinstance(items, list):
            items = []
        normalized = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "id": str(item.get("id") or f"{section}-{index + 1}"),
                    "titre": str(item.get("titre") or "Nouvelle tache"),
                    "details": str(item.get("details") or ""),
                    "fait": bool(item.get("fait")),
                }
            )
        preparation[section] = normalized

    project["preparation"] = preparation
    return project


def normalize_budget(project: dict) -> dict:
    items = project.get("budget")
    if not isinstance(items, list):
        items = []

    normalized = []
    total_estime = 0.0
    total_reel = 0.0
    total_paye = 0.0

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        cout_estime = normalize_money(item.get("cout_estime"), 0.0)
        cout_reel = normalize_money(item.get("cout_reel"), 0.0)
        paye = normalize_money(item.get("paye"), 0.0)
        total_estime += cout_estime
        total_reel += cout_reel
        total_paye += paye
        normalized.append(
            {
                "id": str(item.get("id") or f"budget-{index + 1}"),
                "categorie": str(item.get("categorie") or "General"),
                "item": str(item.get("item") or "Nouvelle depense"),
                "cout_estime": cout_estime,
                "cout_reel": cout_reel,
                "paye": paye,
                "notes": str(item.get("notes") or ""),
            }
        )

    project["budget"] = normalized
    project["budget_resume"] = {
        "total_estime": round(total_estime, 2),
        "total_reel": round(total_reel, 2),
        "total_paye": round(total_paye, 2),
        "reste_a_payer": round(max(total_reel - total_paye, 0.0), 2),
    }
    return project


def visible_guest_lines(project: dict) -> list[str]:
    lines = []
    for invite in project.get("invites", []):
        if not isinstance(invite, dict):
            continue

        statut = str(invite.get("statut") or "").strip()
        presence = str(invite.get("presence") or "").strip()
        if statut == "refuse" or presence == "absent":
            continue

        suffixes = [guest_count_text(invite)]
        if statut == "a_confirmer" or normalize_int(invite.get("nombre_min"), 0) < normalize_int(invite.get("nombre_max"), 0):
            suffixes.append("a confirmer")
        if presence == "present":
            suffixes.append("presence confirmee")
        elif presence == "peut_etre":
            suffixes.append("peut-etre")

        notes = str(invite.get("notes") or "").strip()
        if notes:
            suffixes.append(notes)

        lines.append(f"- {invite_label(invite)} ({', '.join(suffixes)})")
    return lines


def generate_message(project: dict) -> str:
    project = normalize_project(copy.deepcopy(project))
    resume = project.get("resume", {})
    total_min = normalize_int(resume.get("nombre_minimum"), 0)
    total_max = normalize_int(resume.get("nombre_maximum"), total_min)
    present = normalize_int(resume.get("presence_confirmee"), 0)
    unknown = normalize_int(resume.get("presence_inconnue"), 0)
    maybe = normalize_int(resume.get("presence_peut_etre"), 0)
    list_text = "\n".join(visible_guest_lines(project)) or "- Aucune personne dans la liste pour le moment."

    return f"""Bonjour mes compatriotes,

Le message que vous vous appretez a lire est top secret.

Je commence tranquillement a organiser une fete pour celebrer les 25 ans de mariage de mes parents. Je suis presentement en train de preparer la liste des invites et je me demandais a combien de personnes on peut generalement s'attendre pour ce genre d'evenement.

Pour l'instant, selon la liste actuelle, j'arrive a environ {total_min} a {total_max} personnes.

Liste actuelle:

{list_text}

Resume rapide:
- Presences confirmees: {present}
- Peut-etre: {maybe}
- A confirmer / sans reponse: {unknown}

Auriez-vous des suggestions d'amis a Valerie et Vincent?

Gabriel et moi pensions faire un debut au restaurant et une fiesta a la maison pour la suite. En considerant la taille de notre maison, la temperature et la possibilite d'aller dehors, je ne sais pas encore quel serait notre maximum d'invites.
"""


def legacy_invites_payload(project: dict) -> dict:
    project = normalize_project(copy.deepcopy(project))
    return {
        "evenement": project.get("evenement", "25 ans de mariage"),
        "derniere_mise_a_jour": project.get("derniere_mise_a_jour", today()),
        "invites": project.get("invites", []),
        "resume": project.get("resume", {}),
    }


def read_legacy_invites() -> dict:
    if LEGACY_INVITES_PATH.exists():
        with LEGACY_INVITES_PATH.open("r", encoding="utf-8-sig") as file:
            return json.load(file)
    return {"evenement": "25 ans de mariage", "invites": [], "resume": {}}


def read_message_text(project: dict | None = None) -> str:
    if MESSAGE_PATH.exists():
        return MESSAGE_PATH.read_text(encoding="utf-8-sig")
    return generate_message(project or default_project())


def default_project() -> dict:
    try:
        legacy = read_legacy_invites()
    except json.JSONDecodeError:
        legacy = {"evenement": "25 ans de mariage", "invites": [], "resume": {}}

    project = {
        "id": "25ans-mariage",
        "nom": "25 ans mariage",
        "evenement": legacy.get("evenement") or "25 ans de mariage",
        "derniere_mise_a_jour": today(),
        "notes": "Party manager pour les 25 ans de mariage.",
        "invites": legacy.get("invites", []),
        "resume": legacy.get("resume", {}),
        "message": read_message_text({"invites": legacy.get("invites", []), "resume": legacy.get("resume", {})}) if MESSAGE_PATH.exists() else "",
        "preparation": {
            "restaurant": [
                {"id": "restaurant-1", "titre": "Appeler Les Berges", "details": "Verifier disponibilite pour 25 a 35 personnes.", "fait": False},
                {"id": "restaurant-2", "titre": "Verifier le gateau", "details": "Demander si on peut apporter un gateau de l'exterieur.", "fait": False},
                {"id": "restaurant-3", "titre": "Clarifier la facture", "details": "Voir comment gerer groupe, contribution et paiement.", "fait": False},
            ],
            "maison": [
                {"id": "maison-1", "titre": "Acheter chips et cochonneries", "details": "Grignotines pour la fiesta apres le restaurant.", "fait": False},
                {"id": "maison-2", "titre": "Prevoir alcool et boissons sans alcool", "details": "Ajuster selon qui suit a la maison.", "fait": False},
                {"id": "maison-3", "titre": "Preparer jeux de societe, musique et karaoke", "details": "Ambiance relax et festive.", "fait": False},
                {"id": "maison-4", "titre": "Prevoir le gateau", "details": "Decider si le gateau est au restaurant ou a la maison.", "fait": False},
            ],
        },
        "budget": [
            {"id": "budget-1", "categorie": "Restaurant", "item": "Souper Les Berges", "cout_estime": 0, "cout_reel": 0, "paye": 0, "notes": "A estimer selon le nombre de personnes."},
            {"id": "budget-2", "categorie": "Maison", "item": "Chips et cochonneries", "cout_estime": 0, "cout_reel": 0, "paye": 0, "notes": ""},
            {"id": "budget-3", "categorie": "Maison", "item": "Alcool et boissons", "cout_estime": 0, "cout_reel": 0, "paye": 0, "notes": ""},
            {"id": "budget-4", "categorie": "Gateau", "item": "Gateau 25 ans", "cout_estime": 0, "cout_reel": 0, "paye": 0, "notes": ""},
        ],
        "contribution": "Les gens pourront contribuer s'ils le souhaitent comme cadeau de 25e anniversaire.",
    }
    if not project["message"]:
        project["message"] = generate_message(project)
    return normalize_project(project)


def normalize_project(project: dict) -> dict:
    if not isinstance(project, dict):
        project = {}
    project["id"] = slugify(str(project.get("id") or project.get("nom") or "25ans-mariage"))
    project["nom"] = str(project.get("nom") or "25 ans mariage")
    project["evenement"] = str(project.get("evenement") or project["nom"])
    project["derniere_mise_a_jour"] = str(project.get("derniere_mise_a_jour") or today())
    project["notes"] = str(project.get("notes") or "")
    project["message"] = str(project.get("message") or "")
    project["contribution"] = str(project.get("contribution") or "")
    recalculate_invites(project)
    normalize_preparation(project)
    normalize_budget(project)
    return project


def project_path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{slugify(project_id)}.json"


def active_project_id() -> str:
    ensure_dirs()
    if ACTIVE_PROJECT_PATH.exists():
        active = ACTIVE_PROJECT_PATH.read_text(encoding="utf-8").strip()
        if active:
            return slugify(active)
    return "25ans-mariage"


def set_active_project(project_id: str) -> None:
    ensure_dirs()
    ACTIVE_PROJECT_PATH.write_text(slugify(project_id), encoding="utf-8")


def read_project(project_id: str | None = None) -> dict:
    ensure_dirs()
    selected_id = slugify(project_id or active_project_id())
    path = project_path(selected_id)
    if not path.exists():
        project = default_project()
        project["id"] = selected_id if selected_id != "party" else project["id"]
        save_project(project, make_backup=False)
        set_active_project(project["id"])
        return project

    with path.open("r", encoding="utf-8-sig") as file:
        project = json.load(file)
    project = normalize_project(project)
    return project


def sync_legacy_files(project: dict) -> None:
    ensure_dirs()
    LEGACY_INVITES_PATH.write_text(
        json.dumps(legacy_invites_payload(project), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    MESSAGE_PATH.write_text(str(project.get("message") or generate_message(project)).rstrip() + "\n", encoding="utf-8")


def save_project(project: dict, make_backup: bool = True) -> dict:
    ensure_dirs()
    project = normalize_project(copy.deepcopy(project))
    project["derniere_mise_a_jour"] = today()
    path = project_path(project["id"])
    if make_backup and path.exists():
        backup_path = PROJECTS_DIR / f"{project['id']}.backup_{now_stamp()}.json"
        backup_path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")

    path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_active_project(project["id"])
    sync_legacy_files(project)
    return project


def run_git(args: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def git_status_porcelain() -> str:
    code, output = run_git(["status", "--porcelain"])
    if code != 0:
        raise RuntimeError(output or "Impossible de lire le statut Git.")
    return output


def push_to_github(project: dict | None = None) -> dict:
    if project is not None:
        save_project(project)

    status_before = git_status_porcelain()
    committed = False
    commit_output = "Aucun changement a committer."

    if status_before:
        code, output = run_git(["add", "."])
        if code != 0:
            raise RuntimeError(output or "git add a echoue.")

        commit_message = f"Update party project {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        code, commit_output = run_git(["commit", "-m", commit_message])
        if code != 0:
            raise RuntimeError(commit_output or "git commit a echoue.")
        committed = True

    code, pull_output = run_git(["pull", "--rebase", "origin", "main"])
    if code != 0:
        raise RuntimeError(pull_output or "git pull --rebase a echoue.")

    code, push_output = run_git(["push", "origin", "main"])
    if code != 0:
        raise RuntimeError(push_output or "git push a echoue.")

    return {
        "committed": committed,
        "commit_output": commit_output,
        "pull_output": pull_output,
        "push_output": push_output,
    }


def list_projects() -> list[dict]:
    ensure_dirs()
    projects = []
    for path in sorted(PROJECTS_DIR.glob("*.json")):
        if ".backup_" in path.name:
            continue
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                project = normalize_project(json.load(file))
        except (OSError, json.JSONDecodeError):
            continue
        projects.append(
            {
                "id": project["id"],
                "nom": project["nom"],
                "evenement": project["evenement"],
                "derniere_mise_a_jour": project["derniere_mise_a_jour"],
            }
        )
    return projects


class PartyHandler(BaseHTTPRequestHandler):
    server_version = "PartyManager/2.0"

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        return json.loads(raw_body) if raw_body else {}

    def send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Fichier introuvable")
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/project":
                self.send_json(200, read_project())
                return
            if route == "/api/projects":
                self.send_json(200, {"active": active_project_id(), "projects": list_projects()})
                return
            if route == "/api/invites":
                self.send_json(200, legacy_invites_payload(read_project()))
                return
            if route == "/api/message":
                project = read_project()
                self.send_json(200, {"saved": project.get("message", ""), "generated": generate_message(project)})
                return
        except json.JSONDecodeError as error:
            self.send_json(500, {"error": "Un fichier JSON contient une erreur.", "details": str(error)})
            return

        if route in ("/", "/invites_gui.html"):
            self.send_file(HTML_PATH)
            return
        self.send_error(404, "Route introuvable")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            payload = self.read_body()

            if route == "/api/project":
                project = save_project(payload)
                self.send_json(200, {"ok": True, "project": project})
                return

            if route == "/api/projects/load":
                project_id = str(payload.get("id") or "")
                project = read_project(project_id)
                set_active_project(project["id"])
                sync_legacy_files(project)
                self.send_json(200, {"ok": True, "project": project})
                return

            if route == "/api/projects/new":
                name = str(payload.get("nom") or "Nouveau party")
                project = normalize_project(default_project())
                project["id"] = slugify(name)
                project["nom"] = name
                project["evenement"] = name
                project["invites"] = []
                project["resume"] = {}
                project["message"] = generate_message(project)
                project = save_project(project, make_backup=False)
                self.send_json(200, {"ok": True, "project": project})
                return

            if route == "/api/invites":
                project = read_project()
                if isinstance(payload, dict) and "invites" in payload:
                    project["invites"] = payload.get("invites", [])
                    project["resume"] = payload.get("resume", {})
                project = save_project(project)
                self.send_json(200, {"ok": True, "data": legacy_invites_payload(project)})
                return

            if route == "/api/message":
                project = read_project()
                project["message"] = str(payload.get("text") or "")
                project = save_project(project)
                self.send_json(200, {"ok": True, "message": project["message"]})
                return

            if route == "/api/git/push":
                project = payload.get("project") if isinstance(payload, dict) else None
                result = push_to_github(project if isinstance(project, dict) else None)
                self.send_json(200, {"ok": True, **result})
                return

        except json.JSONDecodeError as error:
            self.send_json(400, {"error": "JSON invalide.", "details": str(error)})
            return
        except Exception as error:
            self.send_json(500, {"error": "Operation impossible.", "details": str(error)})
            return

        self.send_error(404, "Route introuvable")

    def log_message(self, format: str, *args) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Party manager local.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=int(os.environ.get("INVITES_GUI_PORT", "8787")), type=int)
    args = parser.parse_args()

    ensure_dirs()
    read_project()
    server = ThreadingHTTPServer((args.host, args.port), PartyHandler)
    print(f"Party manager disponible: http://{args.host}:{args.port}")
    print(f"Projet actif: {project_path(active_project_id())}")
    server.serve_forever()


if __name__ == "__main__":
    main()
