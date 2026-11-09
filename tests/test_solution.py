"""Behavioral regression tests using synthetic snapshots, not practice answers."""
import dataclasses
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'submission'))
import solution


def page(text, url='https://example.test/rates/certificates', title='Certificates'):
    return SimpleNamespace(url=url,title=title,markdown=text,fetched_at='2026-01-01T00:00:00Z')


def snapshot(date, pages, sid=None):
    return SimpleNamespace(snapshot_id=sid or date,taken_on=date,pages=pages)


def certificates(apy='4.12%', dividend='4.03%', term='9 Month', minimum='$800'):
    return ('# Certificates\n\nRegular Certificates\n\n'
            '| Certificate | Dividend Rate | Annual Percentage Yield (APY) | Min. to Earn |\n'
            '| --- | --- | --- | --- |\n'
            f'| {term} | {dividend} | {apy} | {minimum} |\n')


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.ks=solution.build()

    def ingest(self,text,date='2026-01-15',url='https://example.test/rates/certificates'):
        self.ks.ingest(snapshot(date,[page(text,url)]))

    def test_empty_system_and_empty_question(self):
        self.assertFalse(self.ks.answer('certificate APY').confident)
        self.assertFalse(self.ks.answer('').confident)

    def test_apy_and_dividend_are_distinct(self):
        self.ingest(certificates())
        ans=self.ks.answer('9-month certificate APY')
        self.assertIn('4.12%',ans.text)
        self.assertNotIn('4.03%',ans.text)
        self.assertIn('4.03%',self.ks.answer('9-month certificate dividend rate').text)
        self.assertEqual([],self.ks.conflicts())

    def test_historical_floor_and_no_future_leak(self):
        self.ingest(certificates('4.12%'))
        self.ingest(certificates('4.88%'),'2026-03-10')
        for date in ('2026-01-15','2026-02-28','2026-03-09'):
            ans=self.ks.answer('9 month certificate APY',date)
            self.assertIn('4.12%',ans.text)
            self.assertNotIn('4.88%',ans.text)
            self.assertEqual('2026-01-15',ans.sources[0].snapshot_id)
        self.assertIn('4.88%',self.ks.answer('9 month certificate APY','2026-03-10').text)
        self.assertFalse(self.ks.answer('9 month certificate APY','2026-01-01').confident)
        self.assertFalse(self.ks.answer('9 month certificate APY','not-a-date').confident)

    def test_embedded_date_and_explicit_date_precedence(self):
        self.ingest(certificates('4.12%'))
        self.ingest(certificates('4.88%'),'2026-03-10')
        self.assertIn('4.12%',self.ks.answer('What was the 9 month CD APY in January 2026?').text)
        self.assertIn('4.88%',self.ks.answer('What was the 9 month CD APY in January 2026?','2026-03-10').text)

    def test_full_snapshot_removes_deleted_pages(self):
        self.ingest(certificates())
        self.ks.ingest(snapshot('2026-04-01',[]))
        self.assertFalse(self.ks.answer('9 month certificate APY').confident)
        self.assertIn('4.12%',self.ks.answer('9 month certificate APY','2026-02-01').text)

    def test_snapshot_reingestion_replaces_state_and_invalidates_cache(self):
        self.ingest(certificates())
        self.ks.answer('9-month certificate APY')
        self.ingest(certificates('4.77%'))
        self.assertEqual(1,len(self.ks.states))
        self.assertIn('4.77%',self.ks.answer('9-month certificate APY').text)

    def test_as_of_does_not_depend_on_ingestion_order(self):
        self.ingest(certificates('4.88%'),'2026-03-10')
        self.ingest(certificates('4.12%'))
        self.assertIn('4.88%',self.ks.answer('9 month certificate APY').text)

    def test_regular_and_jumbo_are_not_conflicts(self):
        text=certificates()+'| 9 Month Jumbo Certificate | 4.50% | 4.60% | $90000 |\n'
        self.ingest(text)
        ans=self.ks.answer('9-month jumbo certificate APY')
        self.assertIn('4.60%',ans.text)
        self.assertNotIn('4.12%',ans.text)
        self.assertEqual([],self.ks.conflicts())

    def test_unknown_term_and_unknown_jumbo_refuse(self):
        self.ingest(certificates())
        self.assertFalse(self.ks.answer('60 month certificate APY').confident)
        self.assertFalse(self.ks.answer('9 month jumbo certificate APY').confident)

    def test_old_table_schema_preserves_certificate_identity(self):
        text=certificates().replace('Regular Certificates','- Term-Share Certificate Rates\n\nRegular').replace('| Certificate |','| Term |')
        self.ingest(text)
        self.assertIn('4.12%',self.ks.answer('nine month certificate APY').text)

    def test_effective_date_in_future_is_not_current(self):
        self.ingest(certificates()+'\nRates are effective as of 02/01/2026.\n')
        self.assertFalse(self.ks.answer('9 month certificate APY').confident)

    def test_official_source_beats_stale_promotion(self):
        self.ks.ingest(snapshot('2026-01-15',[
            page('9-month certificate APY: 3.11%','https://example.test/promo'),
            page('9-month certificate APY: 4.12%')]))
        ans=self.ks.answer('nine month share certificate APY')
        self.assertIn('4.12%',ans.text)
        self.assertNotIn('3.11%',ans.text)
        self.assertIsNotNone(ans.conflict_note)
        conflicts=self.ks.conflicts()
        self.assertEqual(1,len(conflicts))
        self.assertEqual('4.12%',conflicts[0].resolution)
        self.assertEqual({'3.11%','4.12%'},set(conflicts[0].values))

    def test_expired_offer_is_not_an_answer(self):
        self.ingest('9-month certificate APY: 3.11% (offer ended 2025-12-31)','2026-01-15','https://example.test/promo')
        self.assertFalse(self.ks.answer('9-month certificate APY').confident)

    def test_history_conflicts_have_provenance(self):
        self.ingest(certificates('4.12%'))
        self.ingest(certificates('4.88%'),'2026-03-10')
        conflicts=self.ks.conflicts()
        self.assertEqual(1,len(conflicts))
        self.assertEqual('4.88%',conflicts[0].resolution)
        self.assertIn('historical',conflicts[0].reason.lower())
        self.assertEqual({'2026-01-15','2026-03-10'},{s.snapshot_id for s in conflicts[0].sources})

    def test_numerically_equal_formatting_is_not_conflict(self):
        self.ingest(certificates('4.1%'))
        self.ingest(certificates('4.10%'),'2026-03-10')
        self.assertEqual([],self.ks.conflicts())

    def test_balance_tiers(self):
        text=('\n# Savings\n\n| Account Type | Balance Tier | Dividend Rate | APY |\n'
              '| --- | --- | --- | --- |\n'
              '| Share Savings | $0 - $9,999.99 | 0.11% | 0.12% |\n'
              '| Share Savings | $10,000+ | 0.21% | 0.22% |\n')
        self.ingest(text)
        ans=self.ks.answer('What is the Share Savings APY for $12,000?')
        self.assertIn('0.22%',ans.text)
        self.assertNotIn('0.12%',ans.text)
        self.assertEqual([],self.ks.conflicts())

    def test_auto_model_year_ranges_and_authority(self):
        def auto(model,rate):
            return ('# Auto Loans\n\nAuto Loans\n\n| Loan Program | Term | APR |\n'
                    '| --- | --- | --- |\n'+f'| {model} Model Year | 72 Months | {rate} APR1 |\n')
        self.ks.ingest(snapshot('2026-01-15',[
            page(auto('2022-25','5.71%'),'https://example.test/calculators/auto'),
            page(auto('2023-26','5.91%'),'https://example.test/personal/loans/auto-motorcycle-loans')]))
        ans=self.ks.answer('72-month vehicle APR for a 2024 model')
        self.assertIn('5.91%',ans.text)
        self.assertNotIn('5.71%',ans.text)
        self.assertNotIn('APR1',ans.text)
        self.assertFalse(self.ks.answer('72-month vehicle APR for a 2020 model').confident)
        conflicts=self.ks.conflicts()
        self.assertEqual(1,len(conflicts))
        self.assertEqual({'5.71%','5.91%'},set(conflicts[0].values))
        self.assertEqual('5.91%',conflicts[0].resolution)

    def test_unknown_named_account_does_not_inherit_share_savings(self):
        self.ingest('| Account Type | Balance Tier | APY |\n| --- | --- | --- |\n| Share Savings | $0+ | 0.12% |')
        self.assertFalse(self.ks.answer('Rainbow Savings account APY').confident)

    def test_change_query_returns_observed_timeline(self):
        self.ingest(certificates('4.12%'))
        self.ingest(certificates('4.88%'),'2026-03-10')
        ans=self.ks.answer('How has the 9 month certificate APY changed?')
        for text in ('2026-01-15','2026-03-10','4.12%','4.88%'):
            self.assertIn(text,ans.text)

    def test_future_dated_article_not_used(self):
        self.ingest('March 10, 2026\n\n# Special award\n\nOur credit union won the extraordinary community trophy award.','2026-01-15','https://example.test/newsroom/special-award')
        self.assertFalse(self.ks.answer('Who won the extraordinary community trophy award?').confident)

    def test_old_balance_only_table_keeps_product(self):
        text=("# Savings\n\nInvestor's Choice Money Market\n\n| Balance Tier | APY |\n"
              '| --- | --- |\n| $0 - $999.99 | 0.17% |\n| $1,000+ | 0.27% |')
        self.ingest(text)
        ans=self.ks.answer("Investor's Choice money market APY on $2,000")
        self.assertIn('0.27%',ans.text)
        self.assertNotIn('0.17%',ans.text)

    def test_equally_authoritative_disagreement_is_unresolved(self):
        self.ks.ingest(snapshot('2026-01-15',[
            page(certificates('4.12%'),'https://example.test/rates/a'),
            page(certificates('4.88%'),'https://example.test/rates/b')]))
        ans=self.ks.answer('9-month certificate APY')
        self.assertFalse(ans.confident)
        self.assertNotIn('4.12%',ans.text)
        self.assertNotIn('4.88%',ans.text)
        self.assertIsNone(self.ks.conflicts()[0].resolution)

    def test_intro_and_standard_card_apr_are_not_conflicts(self):
        text=('# Cards\n\n### Platinum Visa\n\n'
              '- Lower ongoing rate: 11.25%-18.25% APR.\n'
              '- New cardmember offer: 1.75% intro APR on transferred balances for 8 months.\n')
        self.ingest(text,url='https://example.test/personal/credit-cards')
        self.assertIn('11.25%',self.ks.answer('Platinum Visa purchase APR').text)
        ans=self.ks.answer('Platinum Visa intro balance transfer APR')
        self.assertIn('1.75%',ans.text)
        self.assertNotIn('11.25%',ans.text)
        self.assertIn('8 months',ans.text)
        self.assertEqual([],self.ks.conflicts())

    def test_unsupported_mortgage_product_refuses(self):
        self.ingest('# Home Loans\n\nConstruction loans are available. Contact a lender.','2026-01-15','https://example.test/personal/loans/home-loans')
        self.assertFalse(self.ks.answer('construction loan rate').confident)
        self.assertFalse(self.ks.answer('7/1 adjustable mortgage APR').confident)

    def test_named_branch_does_not_inherit_general_hours(self):
        self.ingest('# Central Branch\n\nLobby\n\nMonday-Friday: 9 a.m.-5 p.m.\n\nSaturday: Closed',url='https://example.test/newsroom/central-branch')
        self.assertFalse(self.ks.answer('lobby hours for the Imaginary Avenue branch').confident)
        self.assertTrue(self.ks.answer('What are the lobby hours?').confident)

    def test_deterministic_and_defensive_answers(self):
        self.ingest(certificates())
        first=self.ks.answer('nine month CD APY')
        second=self.ks.answer('9-month share certificate APY')
        self.assertEqual(first.text,second.text)
        original=second.sources[0].url
        first.sources[0].url='corrupted'
        self.assertEqual(original,self.ks.answer('nine month CD APY').sources[0].url)

    def test_runtime_has_no_network_requirement(self):
        with patch.object(socket,'socket',side_effect=AssertionError('network access')):
            self.ingest(certificates())
            self.assertIn('4.12%',self.ks.answer('9 month certificate APY').text)


if __name__=='__main__':
    unittest.main()
