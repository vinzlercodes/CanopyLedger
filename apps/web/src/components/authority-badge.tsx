type AuthorityKind = "working" | "frozen" | "published" | "recommendation" | "final" | "unavailable";

const labels: Record<AuthorityKind, string> = {
  working: "Working draft",
  frozen: "Frozen snapshot",
  published: "Published output",
  recommendation: "Recommendation",
  final: "Final decision",
  unavailable: "Unavailable",
};

export function AuthorityBadge({ kind }: { readonly kind: AuthorityKind }) {
  return <span className={`authority authority--${kind}`}>{labels[kind]}</span>;
}
