---
id: rb-cert-rotation
title: Certificate rotation runbook
department: payments
document_type: runbook
access_level: internal
created_date: 2025-09-15
root_cause:
---
This certificate rotation runbook covers the card switch and partner gateway listeners. Renew the certificate in the vault, install it on the listener, and reload the process. Confirm the new certificate with an external handshake before closing the change. Rollback means restoring the previous certificate bundle and reloading the listener again. If the handshake still fails, stop traffic to that partner and follow the payment gateway timeout runbook only if authorizations are timing out rather than failing the TLS handshake. Record the certificate expiry date in the change ticket.
