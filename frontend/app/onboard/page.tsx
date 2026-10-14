import { AuthGate } from "@/components/auth/AuthGate";
import { OnboardingFlow } from "@/components/flow/OnboardingFlow";

export const metadata = {
  title: "Onboard a candidate",
};

/**
 * The immersive flow. Kept off the dashboard shell on purpose: it needs the
 * full viewport for its WebGL layer, and a persistent nav would compete with
 * the 3D agent for attention.
 */
export default function OnboardPage() {
  return (
    <div id="main" tabIndex={-1}>
      <AuthGate>
        <AuthGate>
        <OnboardingFlow />
      </AuthGate>
      </AuthGate>
    </div>
  );
}
