## What I Built
The agent ws built easily based on the Hartwell agent created during lecture. I adjusted the system prompt in accordance with Claude suggestions to tighten the guardrails and give more comprehensive and useful responses. The email runs all ran except for Logan's because he was not in the employee file. Claude suggested adjusting the prompt to allow a run to say that no info is available with employee review flag so he got some type of response but no private information. I did allow this.

## Why This Approach
Four labeled lines. For each of Ridgeline's tasks below, decide what it needs: start with Script, One model call, or Agent, then say why.
Task A: Script - it is repeatable, the same everytime, and doesn't need AI.
Task B: One model call - Can use Claude to rewrite the policy, once, no agent decisions are needed.
Task C: Agent - Needs to look at multiple policies, decide which applies, and provide info to the model to write the emails appropriately.
Email 5 protection: Code. Code supplies the sender so no other balance can be requested.

## Example Run
Sender: danielle.price@ridgelinehotels.example
Subject: A guest
Email: 06-danielle-guest.eml
Organization: ridgeline-hotels
[server] employees.csv: email column 'Email Address'; balance columns 'PTO Days Remaining', 'Sick Days Remaining'
[server] ridgeline-hotels MCP server running (employee mode for danielle.price@ridgelinehotels.example, database C:\Users\srycr\OneDrive\Desktop\GBUS-562-Course\gbus562-coursework\week-04\chroma_dbs\ridgeline-hotels).
Tools offered: search_policy, get_leave_balance, save_reply

--- Step 1: search_policy
Inputs: {"query": "harassment by guest reporting procedure"}
Result: <result rank="1" source="reporting-concerns-and-safety.html" similarity="0.738">
Document: Reporting Concerns and Workplace Safety
Section: Harassment by guests or coworkers

Ridgeline doesn't tolerate harassment of team members by anyone, including guests. If a guest or coworker harasses you, you c...

--- Step 2: search_policy
Inputs: {"query": "retaliation protection for reporting harassment"}
Result: <result rank="1" source="reporting-concerns-and-safety.html" similarity="0.586">
Document: Reporting Concerns and Workplace Safety
Section: Harassment by guests or coworkers

Ridgeline doesn't tolerate harassment of team members by anyone, including guests. If a guest or coworker harasses you, you c...

--- Step 3: save_reply
Inputs: {"reply_text": "(1083 characters, shown below)", "needs_human_review": true}
Result: Draft saved to 06-danielle-guest-20261115-120345.txt. It was not sent.

Claude's final message: I've drafted a reply letting Danielle know People and Culture will follow up directly, and included the relevant facts from the Reporting Concerns and Workplace Safety policy (response timeframe, escalation options, and anti-retaliation protections). I've flagged it for required human review given the harassment and safety nature of her message.

=== Stopped: Claude finished its reply without asking for another tool.
Tool calls used: 3 of 10

=== Draft saved to C:\Users\srycr\OneDrive\Desktop\GBUS-562-Course\gbus562-coursework\week-04\drafts\06-danielle-guest-20261115-120345.txt (not sent)

To: danielle.price@ridgelinehotels.example
Subject: [NEEDS HR REVIEW] Re: A guest
Source email: 06-danielle-guest.eml

DRAFT
Hi Danielle,

Thank you for telling us about this, and I'm sorry you're dealing with it. No one at Ridgeline should have to tolerate this kind of behavior from a guest, and this is being flagged for People and Culture to follow up with you directly.

A few things that may help in the meantime, from our policy on Reporting Concerns and Workplace Safety:

- Ridgeline doesn't tolerate harassment of team members by anyone, including guests. You can report it to your supervisor, any manager, or directly to People and Culture, and a member of People and Culture will contact you within 1 business day of a report (reporting-concerns-and-safety.html).
- If you reported a concern to your supervisor and nothing was done, you can contact People and Culture directly, and you can also call the confidential Team Member Line at any time (reporting-concerns-and-safety.html).
- Ridgeline prohibits retaliation against anyone who reports a concern in good faith (reporting-concerns-and-safety.html).

Someone from People and Culture will be in touch with you soon.

Thank you,
HR Assistant
Needs human review: true

Tokens for this email: 8,176 input, 718 output

## Reflection
Three labeled lines about what your saved runs show.
Email 3 tools: get_leave_balance, search_policy, save_reply. this makes sense because it has to pull the leave balance before it can apply policy against it, and it has to do both of those before drafting a reply.
Email 6 flagged: Yes. The draft told Danielle that People and Culture will follow up and added policy statements from Reporting Concerns and Workplace Safety policy - it did not do this the first run, but suggested editing the prompt to allow it, which I did, so in this run, it did use that policy to state facts without advising. It flagged for human review as well.
Email 7 balance lookup: Error. No employee record for logan so could not return a leave balance. Flagged for human review, said no leave balance could be found and that someone would follow up. 