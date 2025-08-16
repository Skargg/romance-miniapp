# Campus Arc 1 — v7 (with items + expanded premium)

This YAML introduces:
- `items`: purchasable via `scene_shop` (spends gems).
- `requires_item` on certain choices to unlock/boost reactions.
- Expanded premium branch (`scene_p01`..`scene_p06`).

## Backend tasks for Cursor
1) **DB**: add tables `items`, `inventory` (user_id, item_code, qty), and optional `purchases`.
2) **API**:
   - `GET /api/items` -> list items with prices, names (i18n by `lang`).
   - `POST /api/shop/buy` -> spend gems, add to inventory.
   - Inventory check on scene render: disable/grey-out choices with `requires_item` if not owned.
3) **Importer**: allow `items` node in story YAML to seed items table.
4) **Frontend**:
   - Shop modal for `scene_shop`.
   - Show badges for owned items; show 💎 cost on paid choices.

All characters are 18+. Descriptions are suggestive, non-explicit, per Telegram policy.
