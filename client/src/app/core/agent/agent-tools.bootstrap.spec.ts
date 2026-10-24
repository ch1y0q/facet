import { ApplicationInitStatus } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AgentBridgeService } from './agent-bridge.service';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { ServerToolRegistry } from './server-tool-registry.service';
import { provideAgentTools } from './agent-tools.bootstrap';

describe('provideAgentTools', () => {
  it('instantiates the bridge, the WebMCP service and the server tool registry at startup', async () => {
    const created: string[] = [];
    const factory = (name: string) => ({
      provide: name === 'bridge' ? AgentBridgeService : name === 'webmcp' ? AgentWebMcpService : ServerToolRegistry,
      useFactory: () => { created.push(name); return {}; },
    });
    TestBed.configureTestingModule({
      providers: [factory('bridge'), factory('webmcp'), factory('registry'), provideAgentTools()],
    });
    expect(created).toEqual([]);
    await TestBed.inject(ApplicationInitStatus).donePromise;
    expect(created.sort()).toEqual(['bridge', 'registry', 'webmcp']);
  });
});
