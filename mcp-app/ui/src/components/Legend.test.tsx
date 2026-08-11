// @vitest-environment jsdom
import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { describe, it, expect, afterEach } from 'vitest';

afterEach(cleanup);
import { Legend } from './Legend.js';
import { ROLE_LABELS } from '../colors.js';

describe('Legend', () => {
  it('renders all roles in light mode', () => {
    render(<Legend scheme="light" />);
    const legend = screen.getByTestId('legend');
    expect(legend).toBeTruthy();

    // All role labels must be present; 'Unknown' also appears in health section
    // so we use getAllByText for it
    for (const label of Object.values(ROLE_LABELS)) {
      const elements = screen.getAllByText(label);
      expect(elements.length).toBeGreaterThan(0);
    }
  });

  it('renders all roles in dark mode', () => {
    render(<Legend scheme="dark" />);
    for (const label of Object.values(ROLE_LABELS)) {
      const elements = screen.getAllByText(label);
      expect(elements.length).toBeGreaterThan(0);
    }
  });

  it('renders health section labels', () => {
    render(<Legend scheme="light" />);
    expect(screen.getByText('Healthy')).toBeTruthy();
    expect(screen.getByText('Warning')).toBeTruthy();
    expect(screen.getByText('Critical')).toBeTruthy();
    // 'Unknown' appears in both role list and health list
    expect(screen.getAllByText('Unknown').length).toBeGreaterThanOrEqual(2);
  });

  it('renders edge legend', () => {
    render(<Legend scheme="light" />);
    expect(screen.getByText('Same-site flow')).toBeTruthy();
    expect(screen.getByText('Cross-site flow')).toBeTruthy();
    expect(screen.getByText('Width = traffic volume')).toBeTruthy();
  });

  it('has accessible section labels', () => {
    render(<Legend scheme="light" />);
    expect(screen.getByRole('region', { name: 'Role legend' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Health legend' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Edge legend' })).toBeTruthy();
  });
});
