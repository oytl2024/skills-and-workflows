// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/App';
import { ApplicationClient } from '../src/api';
import { fixtureSnapshot } from './fixtures';

afterEach(cleanup);

describe('research workspace (explicit offline fixtures)', () => {
  it.each([1, 2, 4])('renders %i lanes and bounded arrow navigation without commands', count => {
    const client = ApplicationClient.fixture(fixtureSnapshot(count));
    const command = vi.spyOn(client, 'command');
    render(<App client={client} />);
    expect(screen.getByText('离线测试 · 非实时数据')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看离线测试流程 1' }));
    expect((screen.getByRole('button', { name: '上一个流程' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(`1 / ${count}`)).toBeTruthy();
    for (let i = 1; i < count; i++) fireEvent.click(screen.getByRole('button', { name: '下一个流程' }));
    expect((screen.getByRole('button', { name: '下一个流程' }) as HTMLButtonElement).disabled).toBe(true);
    expect(command).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '总览' })).toBeTruthy();
  });

  it('shows a planned node with blank alpha ID, unknown metrics, full expression and settings', () => {
    render(<App client={ApplicationClient.fixture(fixtureSnapshot())} />);
    fireEvent.click(screen.getByRole('button', { name: '查看离线测试流程 1' }));
    const panel = within(screen.getByRole('tabpanel'));
    expect(panel.getByTestId('alpha-id').textContent).toBe('');
    expect(panel.getByText('rank(test_field)')).toBeTruthy();
    expect(panel.getByText(/"region": "USA"/)).toBeTruthy();
    expect(panel.getAllByText('待执行').length).toBeGreaterThan(0);
    expect(panel.getAllByText('未知').length).toBeGreaterThan(0);
  });

  it('retains each lane stage, selected node, scroll and focus on snapshot updates', () => {
    const client = ApplicationClient.fixture(fixtureSnapshot());
    render(<App client={client} />);
    fireEvent.click(screen.getByRole('button', { name: '查看离线测试流程 1' }));
    const child = screen.getByRole('button', { name: /测试处理组/ });
    fireEvent.click(child);
    child.focus();
    const detail = within(screen.getByRole('tabpanel')).getByTestId('node-detail-scroll');
    detail.scrollTop = 125;
    fireEvent.scroll(detail);
    act(() => client.setFixture({ ...fixtureSnapshot(), sequence: 2 }));
    expect(document.activeElement).toBe(child);
    expect(detail.scrollTop).toBe(125);
    fireEvent.click(screen.getByRole('button', { name: '下一个流程' }));
    fireEvent.click(screen.getByRole('tab', { name: /Repair/ }));
    fireEvent.click(screen.getByRole('button', { name: '上一个流程' }));
    expect(screen.getByRole('tab', { name: /Scout/ }).getAttribute('aria-selected')).toBe('true');
    expect(within(screen.getByRole('tabpanel')).getByTestId('alpha-id').textContent).toBe('fixture-alpha');
    expect(within(screen.getByRole('tabpanel')).getByTestId('node-detail-scroll').scrollTop).toBe(125);
    fireEvent.click(screen.getByRole('button', { name: '下一个流程' }));
    expect(screen.getByRole('tab', { name: /Repair/ }).getAttribute('aria-selected')).toBe('true');
  });

  it('shows Seed evidence and an independently scrollable Repair table', () => {
    render(<App client={ApplicationClient.fixture(fixtureSnapshot())} />);
    fireEvent.click(screen.getByRole('button', { name: '查看离线测试流程 1' }));
    fireEvent.click(screen.getByRole('tab', { name: /Seed/ }));
    expect(within(screen.getByRole('tabpanel')).getAllByText('离线门槛通过')).toHaveLength(2);
    fireEvent.click(screen.getByRole('tab', { name: /Repair/ }));
    const table = within(within(screen.getByRole('tabpanel')).getByTestId('repair-scroll')).getByRole('table');
    expect(within(table).getByText('rank(ts_mean(test_field, 5))')).toBeTruthy();
    expect(within(table).getByText('等待离线执行')).toBeTruthy();
  });

  it('shows pending immediately, prevents duplicate Start and displays inline refusal', async () => {
    let reply!: (value: unknown) => void;
    const fetcher = vi.fn().mockImplementation((_url, init) => init?.method === 'POST' ? new Promise(resolve => { reply = resolve; }) : Promise.resolve({ ok: true, json: async () => fixtureSnapshot() }));
    const client = new ApplicationClient({ fetcher, eventSource: null, storage: null });
    render(<App client={client} />);
    await screen.findByText('离线测试目标');
    const start = screen.getByRole('button', { name: /Start/ });
    fireEvent.click(start);
    expect(screen.getByText('正在发送 Start')).toBeTruthy();
    expect((start as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(start);
    await act(async () => reply({ ok: false, json: async () => ({ command_id: JSON.parse(fetcher.mock.calls.find(([, init]) => init?.method === 'POST')![1].body).command_id, status: 'refused', message: '测试：权限不足' }) }));
    expect(screen.getByRole('alert').textContent).toContain('测试：权限不足');
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    client.dispose();
  });
});
