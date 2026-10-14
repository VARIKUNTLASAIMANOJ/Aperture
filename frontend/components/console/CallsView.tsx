"use client";

import { VoicePanel } from "@/components/dash/VoicePanel";
import { AppShell } from "@/components/shell/AppShell";

export function CallsView() {
  // VoicePanel owns its own fetching and polling (the call log is not part of
  // the roster/audit pair), so this view has no data of its own to show.
  return (
    <AppShell title="Voice calls">
      <VoicePanel standalone />
    </AppShell>
  );
}
