## What I Built

I built the tool using the provided prompt in powershell. Larkfield's documents worked, though Claude identified a duplicate file with an earlier version. I left it in for the test run and removed it after Q1 for the rebuild. I also needed to adjust the prompt for Q5 so the tool could deciper the question correctly.

## Why This Approach

Chunking method: Structure
Makes sense on its own: do your chunks make sense when read alone? Yes. They are complete sentences with heading and source. Example chunk from Q6:

Created week-03\\runs\\q6.txt (+40 -0)
Rank 1 | Similarity 0.299 | Source: share-certificates.html
Document: Share Certificates
Section: Dividend rates

* 6-month share certificate: 3.05% annual percentage yield (APY).
* 12-month share certificate: 3.40% APY.
* 24-month share certificate: 3.55% APY.
* 36-month share certificate: 3.60% APY.
* 60-month share certificate: 3.75% APY.

The rate is fixed when the certificate is opened and does not change during the term. Dividends are paid monthly and can stay in the certificate or be transferred to the member's savings or checking account

Label and source: do your chunks carry a label (the document's title and section heading) and their source file? Both. It is shown in the chunks (also see example above).
Short enough: Yes. They are structured but also use natural breaks for longer sections at paragraphs, or for tables/graphics, which are kept in one chunk (separated at a row if needed) and this can be seen during testing.

## Example Run

.venv/Scripts/python.exe week-03/ask.py --docs week-03/larkfield-docs 'Question 2: A member needs a replacement debit card quickly. What does rush delivery cost?' --save week-03/runs/q2.txt

● Bash(cd "/c/Users/srycr/OneDrive/Desktop/GBUS-562-Course/gbus562-coursework" \&\& .venv/Scripts/python.exe week-03/ask.py --docs week-03/larkfield-docs 'Question 2: A…)
Retrieved 4 chunks:

Rank 1 | Similarity 0.570 | Source: consumer-fee-schedule.html
… +23 lines
Created week-03\\runs\\q2.txt (+34 -0)
Rank 1 | Similarity 0.570 | Source: consumer-fee-schedule.html
Document: Consumer Fee Schedule
Section: ATM and debit card fees

Withdrawals at Larkfield ATMs and at CO-OP network ATMs are free. A withdrawal at any other ATM costs $
2, and the ATM's owner may charge its own fee as well. A replacement debit card costs $10, or $30 with
rush delivery. A replacement card is free when the old card was reported lost or stolen because of frau
d.

Document details: Version 8 (current). Replaces Version 7. Owner: Member Services.

Rank 2 | Similarity 0.540 | Source: card-dispute-procedure.html
Document: Debit Card Dispute Procedure
Section: How much the member may have to pay

A member's share of the loss from unauthorized debit card transactions depends on how quickly they repo
rt it. If the member reports a lost or stolen card within two business days of learning about it, they
pay no more than $50. If they report it later than that, they may pay up to $500. If unauthorized trans
actions appear on a statement and the member does not report them within 60 days after the statement wa
s sent, they may have to pay for transactions after those 60 days in full.

Document details: Version 4 (current). Owner: Card Services.

Rank 3 | Similarity 0.511 | Source: card-dispute-procedure.html
Document: Debit Card Dispute Procedure
Section: When a member reports a transaction they did not make

When a member says a debit card transaction on their account was not made or authorized by them, freeze
the card right away in the card system, then open a dispute case. Order a replacement card. The replac
ement is free when the card was used for fraud.

Document details: Version 4 (current). Owner: Card Services.

Rank 4 | Similarity 0.422 | Source: consumer-fee-schedule.html
Document: Consumer Fee Schedule
Section: Statements and account research

Electronic statements are free. Paper statements cost $2 per month. Account research, such as finding a
n old transaction or reconciling an account, costs $20 per hour with a one-hour minimum. A copy of a pa
id check costs $3.

Document details: Version 8 (current). Replaces Version 7. Owner: Member Services.

ANSWER
Rush delivery for a replacement debit card costs $30 \[consumer-fee-schedule.html]. (Note: if the old ca
rd was reported lost or stolen due to fraud, the replacement card is free \[consumer-fee-schedule.html]
\[card-dispute-procedure.html]; the sources do not specify whether the rush delivery fee itself is waive
d in that fraud scenario.)
(timeout 3m)

Rush delivery costs $30, according to consumer-fee-schedule.html. The output is saved to week-03/runs/q2.txt.

* The answer checks out: the fee schedule says "A replacement debit card costs $10, or $30 with rush delivery," and that was the top-ranked chunk. So $30 is the total for the card with rush delivery, not an extra charge on top of the $10.
* Claude's note on fraud cases is fair: a replacement card is free when the old one was reported lost or stolen because of fraud. Neither document says whether the rush charge is also waived, so Claude was right to say so instead of guessing. If a member asks about this, staff would need to check with Card Services.

## Reflection

Four labeled lines, about Questions 1 and 6.
What was wrong: The file that caused the problem was "consumer-fee-schedule-v7.html". Claude did use the correct document but identified the old version and recommended removing it and rebuilding the tool.
How I fixed it: I removed the old version from the documents and rebuilt the tool per Claude's recommendation. Then I reran question 1 to make sure it worked correctly.
Prevention: Larkfield should use Document Ownership assigned to a specific individual and recurring schedule for updates and version control checks in the document repository to ensure the current version is always available and the old version is removed.
Question 6: Declined. Chunks returned included things like dividend rates, fee schedules, share certificates maturity, and service fees on accounts. The tool said no sources contained that information and it could not answer it with available sources.

