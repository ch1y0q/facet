import { JsonSchema } from './ui-tool.types';

function typeMatches(type: string, value: unknown): boolean {
  switch (type) {
    case 'string': return typeof value === 'string';
    case 'integer': return typeof value === 'number' && Number.isInteger(value);
    case 'number': return typeof value === 'number' && Number.isFinite(value);
    case 'boolean': return typeof value === 'boolean';
    case 'null': return value === null;
    case 'array': return Array.isArray(value);
    case 'object': return typeof value === 'object' && value !== null && !Array.isArray(value);
    default: return true;
  }
}

function check(schema: JsonSchema, value: unknown, path: string, issues: string[]): void {
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some(t => typeMatches(t, value))) {
      issues.push(`${path}: expected ${types.join(' or ')}`);
      return;
    }
  }
  if (schema.enum && !schema.enum.includes(value)) {
    issues.push(`${path}: must be one of ${schema.enum.map(v => JSON.stringify(v)).join(', ')}`);
    return;
  }
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) issues.push(`${path}: too short`);
    if (schema.maxLength !== undefined && value.length > schema.maxLength) issues.push(`${path}: too long`);
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) issues.push(`${path}: below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) issues.push(`${path}: above ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) issues.push(`${path}: too few items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) issues.push(`${path}: too many items`);
    const itemSchema = schema.items;
    if (itemSchema) value.forEach((item, i) => check(itemSchema, item, `${path}[${i}]`, issues));
  }
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (!Object.hasOwn(obj, key)) issues.push(`${path}.${key}: required`);
    }
    for (const [key, child] of Object.entries(obj)) {
      const known = schema.properties && Object.hasOwn(schema.properties, key) ? schema.properties[key] : undefined;
      if (known) {
        check(known, child, `${path}.${key}`, issues);
      } else if (schema.additionalProperties === false) {
        issues.push(`${path}.${key}: unknown property`);
      } else if (typeof schema.additionalProperties === 'object') {
        check(schema.additionalProperties, child, `${path}.${key}`, issues);
      }
    }
  }
}

/** Validate `value` against the JSON-Schema subset the UI-tool contract uses. Returns the issues, empty when valid. */
export function validateAgainstSchema(schema: JsonSchema, value: unknown, path = 'args'): string[] {
  const issues: string[] = [];
  check(schema, value, path, issues);
  return issues;
}

/** Fill top-level `default`s for properties the caller left out (the server does the same before forwarding). */
export function withDefaults(schema: JsonSchema, args: Record<string, unknown>): Record<string, unknown> {
  const filled: Record<string, unknown> = { ...args };
  for (const [key, child] of Object.entries(schema.properties ?? {})) {
    if (!Object.hasOwn(filled, key) && child.default !== undefined) filled[key] = child.default;
  }
  return filled;
}
