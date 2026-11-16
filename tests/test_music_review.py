import unittest
from workflow.music_review import evaluate

class MusicReviewTests(unittest.TestCase):
    def records(self):
        return ({'planned_cut':100,'source_span':[70,145],'result':{
            'cut_status':'needs_change','target_music_start':32}},
            {'planned_cut':200,'source_span':[165,245],'result':{
                'cut_status':'needs_change','target_music_end':30}})

    def test_applause_before_intro_or_after_outro_is_not_a_failure(self):
        a,b=self.records();self.assertEqual(evaluate(a,b,[100,200],110,194)['status'],'passed')

    def test_pass_label_cannot_approve_a_truncated_intro(self):
        a,b=self.records();a['result'].update(cut_status='passed',target_music_start=20)
        self.assertEqual(evaluate(a,b,[100,200],110,194)['status'],'needs_change')

    def test_event_before_actual_last_vocal_is_not_accepted(self):
        a,b=self.records();b['result']['target_music_end']=10
        self.assertEqual(evaluate(a,b,[100,200],110,194)['status'],'uncertain')

    def test_old_cut_report_cannot_approve_a_changed_range(self):
        a,b=self.records();self.assertEqual(evaluate(a,b,[98,200],110,194)['status'],'stale')

    def test_wrong_owner_label_cannot_turn_the_next_intro_into_current_outro(self):
        a,b=self.records();b['result']['target_music_end']=None
        b['result']['events']=[
            {'start':0,'end':29,'owner':'previous','description':'female vocals and full band'},
            {'start':29,'end':32,'owner':'previous','description':'instrumental outro fades out'},
            {'start':32,'end':40,'owner':'crowd','description':'cheering and applause'},
            {'start':40,'end':80,'owner':'target','description':'a new acoustic guitar intro'}]
        result=evaluate(a,b,[100,200],110,194)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['observed_finish'],197)

if __name__=='__main__':unittest.main()
