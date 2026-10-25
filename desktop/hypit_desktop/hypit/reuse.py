"""Zero-cost retries: re-use the paid Outputs of an earlier Build.

Hypit has no implicit cache. A new Run must name each earlier Output (`build-record`) and say which
graph position it satisfies (`satisfy`). Which Outputs are worth keeping? The ones that were bought:
those that belong to a component with a Provider request in the Run's price list."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Request ids look like need:author%3A<file>%3A%3Acomponent%3A%3A<component>:<port>
_COMPONENT = re.compile(r"component%3A%3A([^:%]+):")
STATE_FILE = ".hypit-desktop.json"


def paid_components(pricing_json: dict) -> set[str]:
    """Names of the author components that issue paid (Provider) requests."""
    found: set[str] = set()
    for group in pricing_json.get("groups", []):
        for request in group.get("requests", []):
            match = _COMPONENT.search(request.get("request", ""))
            if match:
                found.add(match.group(1))
    return found


def reusable_outputs(outputs: list[dict], components: set[str]) -> list[str]:
    """Public Output names of an earlier Build that belong to a paid component (never a Run target)."""
    names = []
    for output in outputs:
        name = output.get("name", "")
        if output.get("target") or "." not in name:
            continue
        if name.split(".", 1)[0] in components:
            names.append(name)
    return sorted(names)


def _already_satisfied(run_text: str) -> set[str]:
    return set(re.findall(r'<satisfy\s+output="([^"]+)"', run_text))


def write_retry_run(project: Path, original_run: str, build_id: str, names: list[str], new_name: str) -> Path:
    """Copy the Run file and append build-record/satisfy pairs for `names`. Returns the new file."""
    text = (project / original_run).read_text(encoding="utf-8")
    skip = _already_satisfied(text)
    chosen = [n for n in names if n not in skip]
    records = [f'  <build-record id="reuse-{n.replace(".", "-")}" build="{build_id}" output="{n}"/>' for n in chosen]
    satisfies = [f'  <satisfy output="{n}" candidate="reuse-{n.replace(".", "-")}"/>' for n in chosen]
    block = "\n".join(["", "  <!-- reused from an earlier Build so that a retry does not pay again -->", *records, *satisfies, ""])
    closing = text.rindex("</svrun>")
    target = project / new_name
    target.write_text(text[:closing] + block + text[closing:], encoding="utf-8")
    return target


# --- per-project record of what was built, kept next to the Hypit project ---------------------------
def brief_fingerprint(brief: dict) -> str:
    """Identify the request a project was built for; the task id and run bookkeeping do not count."""
    relevant = {k: v for k, v in brief.items() if k not in ("task_id",)}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def load_state(project: Path) -> dict:
    try:
        return json.loads((project / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fingerprint": "", "builds": [], "authored": False}


def save_state(project: Path, state: dict) -> None:
    (project / STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def plan_retry(cli, project: Path, original_run: str, previous_build: str, full_pricing: dict, attempt: int):
    """A Run next to `original_run` that re-uses the paid Outputs of `previous_build`.

    Returns ((run file, estimate, reused count), None) or (None, why not). Never raises for Hypit/IO trouble."""
    from .cli import HypitError
    from .estimate import estimate
    try:
        names = reusable_outputs(cli.outputs(project, previous_build), paid_components(full_pricing))
        if not names:
            return None, "上次没有留下可复用的素材。"
        run_file = (Path(original_run).parent / f"retry-{attempt}.svrun").as_posix()
        write_retry_run(project, original_run, previous_build, names, run_file)
        cli.check(project, run_file)
        return (run_file, estimate(cli.pricing(project, run_file)), len(names)), None
    except (HypitError, OSError, ValueError) as exc:
        return None, " ".join(str(exc).split())[:120]
