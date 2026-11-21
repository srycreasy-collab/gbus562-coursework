## What I Built
I used the same build as Brookfield, but, by adding Copperline, Claude identified a few suggestions for fixing prompts. For most suggestions, I took Claude's advice, which would alter the prompt for both companies. I did not rerun all of Brookline in the interest of cost, but did rerun Copperline multiple times as I made adjustments to the prompts.

## Why This Approach
Four labeled lines about other work at Copperline.
For Tasks A and B, decide what each task needs: start with Script, One model call, Agent, or Team, then say why.
Task A: Agent. The steps depend on the order details, the warranty information found, and then it needs to draft the reply based on those determinations.
Task B: Team. There are several jobs to accomplish - identifying orders that have shipped and drafting a notice to affected customers, and also likely using the number of affected units/customers to include in the safety regulator report. The tone and detail in both reports are different. Additionally, it would likely need a job to find how many orders are affected by units that have NOT yet shipped and drafting a notice, as well as how many units are in stock with no pending orders to pull them from inventory. 
For Tasks C and D, decide which coordinator fits: start with Pipeline or Orchestrator, then say why.
Task C: Pipeline. It is the same code in a fixed order. All steps, every time.
Task D: Orchestrator. It needs to coordinate different specialists based on the requirements of the incoming email and specialists required to handle it.

## Example Run

======================================================================
Orchestrator: 04-pelham-maintenance-closure.eml
From: Owen Brady <o.brady@pelhamfittings.example>
Subject: Plant maintenance closure - PO-5540 not affected
======================================================================
orders.csv columns: ship_day = ship_by_day, product = product, quantity = units
[orchestrator] tokens for this call (claude-sonnet-5): 1,575 in / 720 out

>>> [orchestrator] Choice 1 of at most 10: finish

--- [orchestrator] Step 1: finish
Inputs: {"summary": "Pelham Fittings notified of a one-week plant maintenance closure starting in four weeks. They explicitly confirm PO-5540 (60 SW-3 steam wands) ships before the closure and will arrive on schedule, with no action needed from Copperline. No order impact, no supplier question, and no customer-facing change — no drafts were needed.", "needs_decision": false}
Result: Done.

[orchestrator] A tool ended the run. Tool calls used: 1 of 10.
[orchestrator] Choices, in order: finish

>>> HANDOFF  orchestrator -> drafts folder: C:\Users\srycr\OneDrive\Desktop\GBUS-562-Course\gbus562-coursework\week-05\drafts\copperline-coffee\04-pelham-maintenance-closure-orchestrator-20261120-155658\summary.txt

======================================================================
Summary
======================================================================
Coordinator: orchestrator
Source email: 04-pelham-maintenance-closure.eml
Subject: Plant maintenance closure - PO-5540 not affected

Summary for the purchasing manager:
Pelham Fittings notified of a one-week plant maintenance closure starting in four weeks. They explicitly confirm PO-5540 (60 SW-3 steam wands) ships before the closure and will arrive on schedule, with no action needed from Copperline. No order impact, no supplier question, and no customer-facing change — no drafts were needed.

Needs a decision by a person: no

Drafts (none were sent):
  (none)

Saved C:\Users\srycr\OneDrive\Desktop\GBUS-562-Course\gbus562-coursework\week-05\drafts\copperline-coffee\04-pelham-maintenance-closure-orchestrator-20261120-155658\summary.txt

======================================================================
Orchestrator finished
======================================================================
Drafts saved (0, none sent), in C:\Users\srycr\OneDrive\Desktop\GBUS-562-Course\gbus562-coursework\week-05\drafts\copperline-coffee\04-pelham-maintenance-closure-orchestrator-20261120-155658:
  (none)

Drafts marked for a person (0):
  (none)

Decisions for a person (0):
  (none)

Tokens by role (input / output, calls):
  orchestrator        1,575 /     720  (1 call)
  total               1,575 /     720


## Reflection
Three labeled lines about what your saved runs show.
Email 1 reading: Matches. Diane says the 40 will arrive on the scheduled date (day 4) and the rest 15 days later (day 19), which is also what the brief says.
Email 1 customer names: No. It said it could not provide customer information but did state an impact and asked to expedite any parts earlier than the day 19.
Email 4 orchestrator: None. It only called the finish tool. The pipeline handed off to the analyst and then followed the steps: get_part, get_orders_for_part, then check_coverage. 
