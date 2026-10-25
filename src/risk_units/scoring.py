"""Original maximum one-to-one pairing and metric functions; semantic judgments are external inputs."""
def pair(edges):
    owner={}
    def visit(g,seen):
        for p in edges[g]:
            if p in seen:continue
            seen.add(p)
            if p not in owner or visit(owner[p],seen):owner[p]=g;return True
        return False
    for g in edges:visit(g,set())
    return [{'reference_unit_id':g,'prediction_unit_id':p} for p,g in owner.items()]


def metric(g,p,t):return {'gold':g,'pred':p,'TP':t,'FP':p-t,'FN':g-t,'precision':t/p if p else None,'recall':t/g if g else None,'f1':2*t/(g+p) if g+p else None}
