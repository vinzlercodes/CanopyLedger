export default {
  input: "../docs/api/openapi-v1.json",
  output: "generated/index.ts",
  generator: "scripts/check_typescript_client.py",
} as const;
