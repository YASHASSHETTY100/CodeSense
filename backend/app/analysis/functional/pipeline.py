from .modules import run_module_inference, infer_module_name
from .relations import run_relation_build
from .rules_roles import run_role_rule_detection
from .entities import run_entity_extraction
from sqlalchemy.orm import Session


def run_functional_analysis(db: Session, project_id: int, repo_dir: str) -> dict:
    module_map = run_module_inference(db, project_id)
    n_ent = run_entity_extraction(db, project_id, repo_dir)
    n_rel = run_relation_build(db, project_id, repo_dir, module_map)
    n_roles, n_rules = run_role_rule_detection(db, project_id, repo_dir, module_map)

    # Build and cache domain vocabulary and knowledge graph
    try:
        from app.domain_vocabulary import build_domain_vocabulary, clear_vocab_cache
        from app.knowledge_graph import build_knowledge_graph, clear_graph_cache
        clear_vocab_cache(project_id)
        clear_graph_cache(project_id)
        build_domain_vocabulary(db, project_id, repo_dir)
        build_knowledge_graph(db, project_id, repo_dir)
    except Exception:
        pass

    return {"modules": len(module_map), "entities": n_ent, "relations": n_rel,
            "roles": n_roles, "rules": n_rules}

