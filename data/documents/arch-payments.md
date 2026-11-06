---
id: arch-payments
title: Payments platform architecture
department: payments
document_type: architecture
access_level: internal
created_date: 2025-04-01
root_cause:
---
The payments platform at Harborline Commercial Bank has four runtime services: payment-gateway, card-switch, settlement-batch, and mobile-wallet. The gateway accepts authorization requests and must keep a bounded connection pool toward the card switch. The switch terminates TLS with scheme and partner endpoints. Settlement-batch writes ACH and card clearing files to an isolated volume. Mobile-wallet calls the gateway with an idempotency key tied to the transfer. Namespaces in the knowledge index follow the owning department, and this document lives in the payments namespace. The architecture does not store card numbers in application logs.
