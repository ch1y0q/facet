import { EnvironmentInjector, declareExperimentalWebMcpTool } from '@angular/core';

export type WebMcpDescriptor = Parameters<typeof declareExperimentalWebMcpTool>[0];

export interface WebMcpToolParts {
  name: string;
  description: string;
  inputSchema: object;
  annotations: Record<string, boolean | undefined>;
  execute: (args: unknown) => Promise<string>;
}

/** The one cast from our tool shape to Angular's experimental descriptor, which has to change here if that API does. */
export function toWebMcpDescriptor(parts: WebMcpToolParts): WebMcpDescriptor {
  return parts as unknown as WebMcpDescriptor;
}

/** Register every descriptor on `injector`; one failing registration does not stop the others. */
export function registerWebMcpTools(descriptors: WebMcpDescriptor[], injector: EnvironmentInjector): Promise<unknown> {
  return Promise.allSettled(descriptors.map(descriptor => declareExperimentalWebMcpTool(descriptor, injector)));
}

/** Lower-case hex of `bytes`. */
export function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}
