// An answer from the API that wasn't a success, in the words the service gave for it.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly words: string,
  ) {
    super(words);
  }
}

/** The code as the person typed it: trimmed, spaces out, upper case. */
export const cleanCode = (code: string) => code.replace(/\s+/g, "").toUpperCase();
