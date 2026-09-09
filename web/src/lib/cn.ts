/** Join class names, dropping falsy entries. Small on purpose - the app has no
 *  conditional-class explosion that would justify a dependency. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
