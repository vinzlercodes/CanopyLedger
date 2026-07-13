export type ProjectionTable = {
  readonly title: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly string[])[];
};

function display(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function projectionTables(value: Record<string, unknown>): readonly ProjectionTable[] {
  const tables: ProjectionTable[] = [];
  const visit = (current: unknown, path: readonly string[]) => {
    if (Array.isArray(current) && current.length > 0 && current.every(isRecord)) {
      const columns = [...new Set(current.flatMap((row) => Object.keys(row)))].sort();
      tables.push({ title: path.join(" / "), columns, rows: current.map((row) => columns.map((column) => display(row[column]))) });
      return;
    }
    if (isRecord(current)) Object.entries(current).forEach(([key, nested]) => visit(nested, [...path, key.replaceAll("_", " ")]));
  };
  visit(value, []);
  return tables;
}
