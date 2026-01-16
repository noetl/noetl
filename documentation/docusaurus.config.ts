import { themes as prismThemes } from 'prism-react-renderer';
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'NoETL',
  tagline: 'Automation framework for orchestrating APIs, databases, and scripts using a declarative Playbook DSL',
  favicon: 'img/favicon.ico',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Production URL for noetl.dev
  url: 'https://noetl.dev',
  // Set the /<baseUrl>/ pathname under which your site is served
  baseUrl: '/',

  // GitHub pages deployment config.
  organizationName: 'noetl', // GitHub org name.
  projectName: 'noetl', // Repo name.

  onBrokenLinks: 'warn',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  // https://github.com/cmfcmf/docusaurus-search-local
  plugins: [
    [
      "@cmfcmf/docusaurus-search-local",
      {
        indexBlog: false, // Blog is disabled
      },
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Exclude YAML playbook files (they're reference examples, not docs)
          exclude: ['**/*.yaml', '**/*.yml'],
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/noetl/noetl/edit/master/documentation/',
        },
        blog: false, // Disabled - no blog content yet
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // Replace with your project's social card
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'NoETL',
      logo: {
        alt: 'NoETL Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          type: 'docSidebar',
          sidebarId: 'examplesSidebar',
          position: 'left',
          label: 'Examples',
        },
        {
          href: 'https://github.com/noetl/noetl',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'Getting Started',
              to: '/docs/intro',
            },
            {
              label: 'DSL Reference',
              to: '/docs/reference/dsl/',
            },
            {
              label: 'CLI Reference',
              to: '/docs/reference/noetl_cli_usage',
            },
          ],
        },
        {
          title: 'Examples',
          items: [
            {
              label: 'Authentication',
              to: '/docs/examples/authentication/',
            },
            {
              label: 'Data Transfer',
              to: '/docs/examples/data-transfer/',
            },
            {
              label: 'Pagination',
              to: '/docs/examples/pagination/',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Issues',
              href: 'https://github.com/noetl/noetl/issues',
            },
            {
              label: 'Discussions',
              href: 'https://github.com/noetl/noetl/discussions',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/noetl/noetl',
            },
            {
              label: 'Releases',
              href: 'https://github.com/noetl/noetl/releases',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} NoETL Project. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
