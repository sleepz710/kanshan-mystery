"""离线联调剧本，固定回复不代表真实模型生成质量。"""


def mock_story() -> dict:
    return {
        "id": "mock-letter", "title": "模拟剧场：消失的信", "source": "generated",
        "intro": "信封还在会议桌上，里面的信不见了。三个人都说没有取走它。",
        "facts": [
            {"id": "f1", "text": "秘书林青把信寄给陈明。"},
            {"id": "f2", "text": "陈明已在当天签收信件。"},
            {"id": "f3", "text": "保安王平在换班时见证林青寄出信件。"}],
        "characters": [
            {"id": "lin", "name": "林青", "avatar": "lin.png", "profile": "秘书", "persona": "谨慎，想保护收件人", "knows": ["f1"], "secrets": [], "lies": [
                {"id": "l1", "claim": "我没碰过信", "until": {"shown": "c1"}, "admit": "f1"}], "trust_start": 0},
            {"id": "chen", "name": "陈明", "avatar": "chen.png", "profile": "收件人", "persona": "紧张，想隐瞒收信", "knows": ["f2"], "secrets": [], "lies": [
                {"id": "l2", "claim": "我没有收到任何东西", "until": {"shown": "c2"}, "admit": "f2"}], "trust_start": 0},
            {"id": "wang", "name": "王平", "avatar": "wang.png", "profile": "保安", "persona": "坦率", "knows": ["f3"], "secrets": [], "lies": [], "trust_start": 0}],
        "clues": [
            {"id": "c1", "title": "监控记录", "content": "林青取出信件交给快递员。", "holder": "wang"},
            {"id": "c2", "title": "快递回执", "content": "陈明于当日签收信件。", "holder": "lin", "requires": {"exposed": "l1"}},
            {"id": "c3", "title": "空信封", "content": "封口整齐打开，并非被撕毁。", "holder": "wang"},
            {"id": "c4", "title": "寄件单", "content": "寄件人林青，收件人陈明。", "holder": "lin", "requires": {"trust": 1}},
            {"id": "c5", "title": "收件登记", "content": "陈明签收的时间是下午两点。", "holder": "chen", "requires": {"exposed": "l2"}},
            {"id": "c6", "title": "换班记录", "content": "寄件时保安王平正在换班，见证林青寄信。", "holder": "wang", "requires": {"trust": 1}},
            {"id": "c7", "title": "走廊记录", "content": "林青没有带着信离开办公楼，是快递员取走的。", "holder": "wang"},
            {"id": "c8", "title": "对质记录", "content": "林青和陈明承认信已通过快递送达。", "holder": "chen", "requires": {"event": "e1"}}],
        "events": [{"id": "e1", "when": {"shown": "c2", "to": "chen"}, "confront": ["lin", "chen"], "unlock": ["c8"]}],
        "kanshan": {"greeting": "搭档，先找在场的人问问。", "hints": [
            {"done": {"exposed": "l1"}, "vague": "监控也许拍下了什么。", "direct": "找王平拿监控，出示给林青。"},
            {"done": {"exposed": "l2"}, "vague": "快递会有回执。", "direct": "把快递回执出示给陈明。"}]},
        "ending": {"questions": [
            {"id": "q1", "text": "谁从信封取出信件？", "options": ["林青", "陈明", "王平"], "answer": "林青"},
            {"id": "q2", "text": "谁收到了信？", "options": ["林青", "陈明", "王平"], "answer": "陈明"},
            {"id": "q3", "text": "寄信时谁在换班并见证寄件？", "options": ["林青", "陈明", "王平"], "answer": "王平"}],
            "endings": [
                {"id": "truth", "title": "信的去向", "when": {"correct": ["q1", "q2", "q3"]}, "text": "完整证据链证明信已寄出并签收。"},
                {"id": "wrong", "title": "误会", "when": {"chose": {"q1": "王平"}}, "text": "你怀疑了无辜的保安。", "retry": True},
                {"id": "half", "title": "尚未查清", "text": "还有细节没有解释。", "retry": True}],
            "truth": "林青取出信件，交给快递员寄到陈明手中；换班的王平见证了寄件。", "lessons": []},
    }
