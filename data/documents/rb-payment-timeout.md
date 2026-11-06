---
id: rb-payment-timeout
title: Runbook for payment gateway timeouts
department: payments
document_type: runbook
access_level: internal
created_date: 2025-08-01
root_cause:
---
Use this runbook when the payment gateway timeout rate exceeds five percent for three minutes. First confirm whether the card switch is healthy. Then inspect connection pool exhaustion metrics on the gateway. If the pool is saturated, shed duplicate retries and raise the ceiling only for the duration of the incident. Tell merchant support to expect authorization retries. Do not restart the ledger. After recovery, file an incident report with the root cause and link any earlier payment gateway timeout incidents.
