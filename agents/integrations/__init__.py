"""Harici entegrasyonlar - anahtar yoksa yerel dosyaya dusen zarif iskeletler."""

from __future__ import annotations

from agents.integrations.ntfy import Ntfy
from agents.integrations.supabase_sync import SupabaseSync

__all__ = ["Ntfy", "SupabaseSync"]
