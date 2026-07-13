import { CanopyLedgerClient, type ApiResponse, type ProblemDetails } from "../../../../../typescript/generated/index";

const bearerToken = /^Bearer\s+[^\s]+$/i;

export class ApiProblem extends Error {
  readonly code?: string;
  readonly status: number;

  constructor(status: number, body: ProblemDetails | undefined) {
    super(body?.detail || body?.title || "The CanopyLedger API request failed.");
    this.name = "ApiProblem";
    this.code = body?.code;
    this.status = status;
  }
}

export function forwardedAuthorization(value: string | null): Record<string, string> {
  return value !== null && bearerToken.test(value) ? { Authorization: value } : {};
}

export function createApiClient(authorization: string | null): CanopyLedgerClient {
  return new CanopyLedgerClient({
    baseUrl: process.env.CANOPYLEDGER_API_BASE_URL ?? "http://127.0.0.1:8000",
    defaultHeaders: forwardedAuthorization(authorization),
  });
}

export function requireSuccess<T>(response: ApiResponse<T>): T {
  if (response.status >= 200 && response.status < 300) {
    return response.data;
  }

  throw new ApiProblem(response.status, response.data as ProblemDetails);
}
