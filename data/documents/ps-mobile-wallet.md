---
id: ps-mobile-wallet
title: Mobile wallet product specification
department: payments
document_type: specification
access_level: internal
created_date: 2026-01-20
root_cause:
---
The mobile wallet lets a customer pay a merchant or top up a stored balance. Every transfer carries an idempotency key that is unique for the amount, source, and destination. The wallet must show a clear failure when the payment gateway times out, and it must not silently retry with a new key. Product analytics may report decline rates to analysts. Viewers of this specification should not expect customer account numbers; the wallet stores a token, not a card number.
