import { EnvironmentProviders, inject, provideAppInitializer } from '@angular/core';
import { AgentBridgeService } from './agent-bridge.service';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { ServerToolRegistry } from './server-tool-registry.service';

/** Instantiates both agent consumers at startup; each decides on its own (auth + `features.mcp`) whether to act. */
export function provideAgentTools(): EnvironmentProviders {
  return provideAppInitializer(() => {
    inject(AgentBridgeService);
    inject(AgentWebMcpService);
    inject(ServerToolRegistry);
  });
}
