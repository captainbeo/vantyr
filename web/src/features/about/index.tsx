/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowRight,
  CircleDollarSign,
  Code2,
  Globe2,
  KeyRound,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { PublicLayout } from '@/components/layout'
import { RichContent } from '@/components/rich-content'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { isHttpUrl, isLikelyHtml } from '@/lib/content-format'
import { requireServerSuccess } from '@/lib/server-error-message'
import { useAuthStore } from '@/stores/auth-store'

import { getAboutContent } from './api'

interface AboutCard {
  icon: ReactNode
  title: string
  description: string
}

function AboutHero() {
  const { t } = useTranslation()
  const isAuthenticated = Boolean(useAuthStore((state) => state.auth.user))
  const primaryHref = isAuthenticated ? '/dashboard' : '/sign-up'
  const primaryLabel = isAuthenticated ? t('Go to Dashboard') : t('Get API key')

  return (
    <section className='relative overflow-hidden border-b'>
      <div
        aria-hidden
        className='pointer-events-none absolute inset-0 opacity-60 dark:opacity-30'
        style={{
          background:
            'radial-gradient(ellipse 55% 80% at 85% 10%, color-mix(in oklch, var(--primary) 14%, transparent), transparent 70%)',
        }}
      />
      <div className='relative mx-auto grid max-w-7xl gap-10 px-5 py-20 md:py-28 lg:grid-cols-[1.2fr_0.8fr] lg:items-end'>
        <div>
          <p className='label-mono'>
            <span className='text-primary'>ABOUT-00</span> / {t('Vantyr')}
          </p>
          <h1 className='font-display mt-5 max-w-4xl text-5xl leading-[0.98] font-semibold md:text-7xl'>
            {t('The real models.')}{' '}
            <span className='text-primary'>
              {t('97% less than official rates.')}
            </span>
          </h1>
          <p className='text-muted-foreground mt-6 max-w-2xl text-lg leading-relaxed'>
            {t(
              'Vantyr gives you genuine Claude and Codex access at up to 97% below official rates, without fixed monthly subscriptions, arbitrary usage caps or regional lockouts.'
            )}
          </p>
          <div className='mt-8 flex flex-wrap items-center gap-3'>
            <Button
              className='rounded-sm font-mono tracking-wider uppercase'
              render={<Link to={primaryHref} />}
            >
              {primaryLabel}
              <ArrowRight className='ml-1.5 size-4' />
            </Button>
            <Button
              variant='outline'
              className='rounded-sm font-mono tracking-wider uppercase'
              render={<Link to='/pricing' />}
            >
              {t('View Pricing')}
            </Button>
          </div>
        </div>

        <div data-slot='glass-box' className='bg-card grid grid-cols-2 divide-border divide-x divide-y rounded-sm border font-mono text-xs'>
          <div className='p-5'>
            <div className='label-mono'>{t('Billing model')}</div>
            <div className='font-display mt-2 text-2xl font-semibold'>
              {t('Pay-as-you-go')}
            </div>
          </div>
          <div className='p-5'>
            <div className='label-mono'>{t('Usage ceilings')}</div>
            <div className='font-display text-primary mt-2 text-2xl font-semibold'>
              {t('None')}
            </div>
          </div>
          <div className='p-5'>
            <div className='label-mono'>{t('Model access')}</div>
            <div className='font-display mt-2 text-2xl font-semibold'>
              Claude + Codex
            </div>
          </div>
          <div className='p-5'>
            <div className='label-mono'>{t('Budget stretch')}</div>
            <div className='font-display text-primary mt-2 text-2xl font-semibold'>
              {t('More usage')}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function BudgetSection() {
  const { t } = useTranslation()

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <p className='label-mono'>
          <span className='text-primary'>PRICE-00</span> /{' '}
          {t('Make your budget go further')}
        </p>
        <div className='mt-3 grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end'>
          <div>
            <h2 className='font-display text-3xl font-semibold md:text-5xl'>
              {t('Up to 97% cheaper than official Claude and Codex API rates.')}
            </h2>
            <p className='text-muted-foreground mt-4 max-w-xl text-sm leading-relaxed'>
              {t(
                'The money you put toward a Claude or Codex subscription can go much further at Vantyr: top up once, pay only for the requests you run, and keep the rest for your next task.'
              )}
            </p>
          </div>
          <div data-slot='glass-box' className='bg-card grid rounded-sm border divide-border divide-y font-mono text-xs md:grid-cols-2 md:divide-x md:divide-y-0'>
            <div className='p-5'>
              <div className='label-mono'>{t('Official subscriptions')}</div>
              <h3 className='font-display mt-3 text-xl font-semibold'>
                {t('Pay monthly, then hit a ceiling')}
              </h3>
              <p className='text-muted-foreground mt-2 leading-relaxed'>
                {t('A fixed bill buys access to a plan, not unlimited work.')}
              </p>
            </div>
            <div className='p-5'>
              <div className='label-mono text-primary'>{t('Vantyr PAYG')}</div>
              <h3 className='font-display mt-3 text-xl font-semibold'>
                {t('Pay less, run more')}
              </h3>
              <p className='text-muted-foreground mt-2 leading-relaxed'>
                {t(
                  'Your balance is spent on real model usage, so the same budget can fund substantially more requests.'
                )}
              </p>
            </div>
          </div>
        </div>
        <p className='text-muted-foreground/70 mt-6 font-mono text-[11px]'>
          {t(
            'Savings vary by model and usage mix; published prices are shown before you send a request.'
          )}
        </p>
      </div>
    </section>
  )
}

function ProblemSection() {
  const { t } = useTranslation()

  const problems: AboutCard[] = [
    {
      icon: <CircleDollarSign className='size-5' aria-hidden='true' />,
      title: t('Fixed monthly price'),
      description: t(
        'Claude and ChatGPT subscriptions charge every month whether you use them or not, then stop you when you hit an opaque allowance. The same money buys more requests at Vantyr rates.'
      ),
    },
    {
      icon: <LockKeyhole className='size-5' aria-hidden='true' />,
      title: t('Hard usage limits'),
      description: t(
        'Rate-limit windows and weekly caps interrupt long coding sessions exactly when you need throughput.'
      ),
    },
    {
      icon: <Globe2 className='size-5' aria-hidden='true' />,
      title: t('Regional restrictions'),
      description: t(
        'Plans, payment methods and model access are unavailable in many countries, even when the underlying models would work.'
      ),
    },
    {
      icon: <KeyRound className='size-5' aria-hidden='true' />,
      title: t('One account per vendor'),
      description: t(
        'Every provider wants its own subscription, app and set of limits to keep track of.'
      ),
    },
  ]

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <p className='label-mono'>
          <span className='text-primary'>WHY-00</span> / {t('The problem')}
        </p>
        <h2 className='font-display mt-3 max-w-4xl text-3xl font-semibold md:text-5xl'>
          {t('Subscriptions are convenient until your work depends on them.')}
        </h2>
        <div data-slot='glass-box' className='bg-card mt-12 grid divide-border divide-y rounded-sm border md:grid-cols-2 md:divide-x md:divide-y-0'>
          {problems.map((problem) => (
            <article key={problem.title} className='p-6 md:p-8'>
              <div className='text-primary'>{problem.icon}</div>
              <h3 className='font-display mt-5 text-xl font-semibold'>
                {problem.title}
              </h3>
              <p className='text-muted-foreground mt-2 text-sm leading-relaxed'>
                {problem.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

function SolutionSection() {
  const { t } = useTranslation()

  const solutions: AboutCard[] = [
    {
      icon: <CircleDollarSign className='size-5' aria-hidden='true' />,
      title: t('Pay only for what you use'),
      description: t(
        'Top up a balance and pay per request and token — up to 97% below official rates. No monthly fee, no wasted allowance, no surprise renewal.'
      ),
    },
    {
      icon: <Waypoints className='size-5' aria-hidden='true' />,
      title: t('One key, every model'),
      description: t(
        'A single API key routes to genuine Claude and Codex models. Switch models per project or per request.'
      ),
    },
    {
      icon: <Code2 className='size-5' aria-hidden='true' />,
      title: t('Drop-in compatible'),
      description: t(
        'Point Claude Code, Codex CLI, your SDK or your own application at Vantyr. Request and response shapes stay familiar.'
      ),
    },
    {
      icon: <ShieldCheck className='size-5' aria-hidden='true' />,
      title: t('Real models, transparent service'),
      description: t(
        'We do not quietly swap, distill or downgrade models. Prices, usage and request outcomes remain visible in your dashboard.'
      ),
    },
  ]

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <p className='label-mono'>
          <span className='text-primary'>WHAT-00</span> / {t('The Vantyr way')}
        </p>
        <h2 className='font-display mt-3 max-w-4xl text-3xl font-semibold md:text-5xl'>
          {t('One gateway for the tools you already use.')}
        </h2>
        <div data-slot='glass-box' className='bg-card mt-12 grid divide-border divide-y rounded-sm border md:grid-cols-2 md:divide-x md:divide-y-0'>
          {solutions.map((solution) => (
            <article key={solution.title} className='p-6 md:p-8'>
              <div className='text-primary'>{solution.icon}</div>
              <h3 className='font-display mt-5 text-xl font-semibold'>
                {solution.title}
              </h3>
              <p className='text-muted-foreground mt-2 text-sm leading-relaxed'>
                {solution.description}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

function StepsSection() {
  const { t } = useTranslation()

  const steps = [
    {
      number: '01',
      title: t('Create an account'),
      description: t('Sign up and create your personal Vantyr API key.'),
    },
    {
      number: '02',
      title: t('Top up your balance'),
      description: t(
        'Add credit when you need it and keep full control of your spend.'
      ),
    },
    {
      number: '03',
      title: t('Keep building'),
      description: t(
        'Swap the base URL, choose a model and continue your workflow.'
      ),
    },
  ]

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-20'>
        <p className='label-mono'>
          <span className='text-primary'>START-00</span> / {t('Integration')}
        </p>
        <h2 className='font-display mt-3 text-3xl font-semibold md:text-4xl'>
          {t('Three steps. No rewrite.')}
        </h2>
        <ol data-slot='glass-box' className='bg-card mt-10 grid list-none divide-border divide-y rounded-sm border md:grid-cols-3 md:divide-x md:divide-y-0'>
          {steps.map((step) => (
            <li key={step.number} className='p-6'>
              <div className='text-primary font-mono text-sm'>
                {step.number}
              </div>
              <h3 className='font-display mt-6 text-xl font-semibold'>
                {step.title}
              </h3>
              <p className='text-muted-foreground mt-2 text-sm leading-relaxed'>
                {step.description}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function Attribution() {
  const { t } = useTranslation()

  return (
    <section className='border-b'>
      <div className='mx-auto max-w-7xl px-5 py-10'>
        <div className='text-muted-foreground flex flex-col gap-2 font-mono text-[11px] leading-relaxed md:flex-row md:items-center md:justify-between'>
          <p>
            {t('Frontend design and development by New API contributors.')}{' '}
            <a
              href='https://github.com/QuantumNous/new-api'
              target='_blank'
              rel='noopener noreferrer'
              className='text-primary hover:underline'
            >
              https://github.com/QuantumNous/new-api
            </a>
          </p>
          <p>
            {t('This project must be used in compliance with the')}{' '}
            <a
              href='https://github.com/QuantumNous/new-api/blob/main/LICENSE'
              target='_blank'
              rel='noopener noreferrer'
              className='text-primary hover:underline'
            >
              {t('AGPL v3.0 License')}
            </a>
            .
          </p>
        </div>
      </div>
    </section>
  )
}

function EmptyAboutState() {
  const { t } = useTranslation()
  const isAuthenticated = Boolean(useAuthStore((state) => state.auth.user))
  const ctaHref = isAuthenticated ? '/dashboard' : '/sign-up'
  const ctaLabel = isAuthenticated ? t('Go to Dashboard') : t('Get API key')

  return (
    <div className='relative z-10 overflow-hidden'>
      <AboutHero />
      <BudgetSection />
      <ProblemSection />
      <SolutionSection />
      <StepsSection />
      <Attribution />
      <section>
        <div className='mx-auto flex max-w-7xl flex-col items-start justify-between gap-6 px-5 py-16 md:flex-row md:items-center'>
          <div>
            <p className='label-mono'>
              <Sparkles
                className='text-primary mr-2 inline-block size-3'
                aria-hidden='true'
              />
              VANTYR
            </p>
            <h2 className='font-display mt-3 text-3xl font-semibold md:text-4xl'>
              {t('Ready to get more from your AI budget?')}
            </h2>
          </div>
          <Button
            className='rounded-sm font-mono tracking-wider uppercase'
            render={<Link to={ctaHref} />}
          >
            {ctaLabel}
            <ArrowRight className='ml-1.5 size-4' />
          </Button>
        </div>
      </section>
    </div>
  )
}

export function About() {
  const { t } = useTranslation()
  const { data, isLoading } = useQuery({
    queryKey: ['about-content'],
    queryFn: async () => requireServerSuccess(await getAboutContent()),
  })

  const rawContent = data?.data?.trim() ?? ''
  const hasContent = rawContent.length > 0
  const isUrl = hasContent && isHttpUrl(rawContent)
  const contentIsHtml = hasContent && isLikelyHtml(rawContent)

  if (isLoading) {
    return (
      <PublicLayout>
        <div className='mx-auto flex max-w-4xl flex-col gap-4 py-12'>
          <Skeleton className='h-8 w-[45%]' />
          <Skeleton className='h-4 w-full' />
          <Skeleton className='h-4 w-[90%]' />
          <Skeleton className='h-4 w-[80%]' />
        </div>
      </PublicLayout>
    )
  }

  if (!hasContent) {
    return (
      <PublicLayout showMainContainer={false}>
        <EmptyAboutState />
      </PublicLayout>
    )
  }

  if (isUrl) {
    return (
      <PublicLayout showMainContainer={false}>
        <iframe
          src={rawContent}
          className='h-[calc(100vh-3.5rem)] w-full border-0'
          title={t('About')}
          sandbox='allow-forms allow-popups allow-popups-to-escape-sandbox allow-scripts'
        />
      </PublicLayout>
    )
  }

  if (contentIsHtml) {
    return (
      <PublicLayout showMainContainer={false}>
        <RichContent
          mode='html'
          htmlVariant='isolated'
          content={rawContent}
          className='prose-neutral dark:prose-invert max-w-none'
        />
      </PublicLayout>
    )
  }

  return (
    <PublicLayout>
      <div className='mx-auto max-w-6xl px-4 py-8'>
        <RichContent
          mode='markdown'
          content={rawContent}
          className='prose-neutral dark:prose-invert max-w-none'
        />
      </div>
    </PublicLayout>
  )
}
