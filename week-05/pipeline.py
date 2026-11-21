"""Coordinator 1: a fixed pipeline that prepares a company's response to one supplier email.

The same steps run for every email, in this order:

    1. Supply analyst      works out how the email affects customer orders (JSON brief).
    2. Customer writer     drafts a notice for each order at risk in the brief; skipped if
                           there are none. Orders that only some of a supplier's options put
                           at risk get no notice: a person chooses the option first, which
                           may avoid the delay.
    3. Supplier writer     drafts the reply to the supplier; nothing is saved if it says
                           NO REPLY NEEDED.

Every draft goes through the review step in specialists.py (reviewer, up to two
revisions, name check in code) and is saved to
week-05/drafts/<company folder>/<email>-pipeline-<time>/. Nothing is ever sent. At the
end the pipeline prints a summary: drafts saved, drafts marked for a person, decisions
for a person, and total tokens.

Run from the top of the repository:

    .venv\\Scripts\\python.exe week-05\\pipeline.py --email week-05\\brookfield-bikes\\supplier-emails\\01-northgate-controller-delay.eml
    .venv\\Scripts\\python.exe week-05\\pipeline.py --org week-05\\copperline-coffee --email week-05\\copperline-coffee\\supplier-emails\\01-danforth-pump-delay.eml

--org FOLDER names a company folder laid out like week-05/brookfield-bikes (the default).
Add --save FILE to also write everything printed to FILE (UTF-8).
"""

import sys

from agent_loop import banner, run_cli
from specialists import Team, option_order_ids


def pipeline_summary(team):
    """The summary for the purchasing manager, built by code from the brief (saved in summary.txt)."""
    brief = team.brief
    lines = [f"Part {brief['part_id']}: {brief['what_changed']}"]
    if brief["orders_at_risk"]:
        lines.append("Orders at risk:")
        for row in brief["orders_at_risk"]:
            penalty = row.get("late_penalty")
            penalty_text = " (late penalty)" if str(penalty).lower() in {"true", "yes"} else ""
            lines.append(
                f"  - {row.get('order_id')} {row.get('customer', '')}: {row.get('units_short')} units short, "
                f"ship day {row.get('ship_day')}, ready day {row.get('ready_day')}{penalty_text}"
            )
    else:
        lines.append(f"No customer orders are at risk whatever {team.name} decides.")
    for option in brief["options"]:
        if isinstance(option, dict):
            ids = ", ".join(option_order_ids(option)) or "none"
            lines.append(f"{option.get('name')}: puts at risk {ids}")
    for decision in brief["decisions_for_a_person"]:
        lines.append(f"Decision needed: {decision}")
    for question in brief["supplier_questions"]:
        lines.append(f"Supplier asked: {question}")
    return "\n".join(lines)


def print_final_summary(team, usage, title="Pipeline finished"):
    """Printed at the end of a run; orchestrator.py uses it too."""
    banner(title)
    print(f"Drafts saved ({len(team.drafts)}, none sent), in {team.run_dir or 'no folder: nothing was saved'}:")
    for draft in team.drafts:
        print(f"  - {draft['file']} to {draft['to']}")
    if not team.drafts:
        print("  (none)")

    marked = [d for d in team.drafts if d["for_person"]]
    print(f"\nDrafts marked for a person ({len(marked)}):")
    for draft in marked:
        print(f"  - {draft['file']}: {'; '.join(draft['for_person'])}")
    if not marked:
        print("  (none)")

    decisions = [str(d) for d in team.brief["decisions_for_a_person"]] if team.brief is not None else []
    if team.brief_problems:
        decisions.append("Check the analyst's brief: it doesn't match the tool results (" + "; ".join(team.brief_problems) + ").")
    print(f"\nDecisions for a person ({len(decisions)}):")
    for decision in decisions:
        print(f"  - {decision}")
    if not decisions:
        print("  (none)")

    print()
    print(usage.report())
    usage.reported = True  # run_cli doesn't print it again


async def coordinate(client, usage, company_dir, email, email_path):
    banner(f"Pipeline: {email.label}\nFrom: {email.reply_to}\nSubject: {email.subject}")
    team = Team(client, usage, company_dir, email, email_path, coordinator="pipeline")

    # 1. Supply analyst.
    brief = await team.run_analyst(email)

    # 2. A customer notice for each order at risk, if any.
    order_ids = list(dict.fromkeys(str(r.get("order_id")).strip() for r in brief["orders_at_risk"]))
    if order_ids:
        for order_id in order_ids:
            await team.draft_customer_notice(order_id)
    else:
        banner("Customer writer")
        print(f"No orders are at risk whatever {team.name} decides, so no customer notices are drafted.")

    # 3. The reply to the supplier.
    await team.draft_supplier_reply()

    team.write_summary(pipeline_summary(team), needs_decision=bool(brief["decisions_for_a_person"] or brief["options"]))
    print_final_summary(team, usage)
    return 0


if __name__ == "__main__":
    sys.exit(run_cli("Fixed pipeline: prepare a company's response to one supplier email.", coordinate))
