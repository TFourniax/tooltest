"""French human help; commands and machine terms remain canonical."""

GUIDED_HELP_FR = """DiffWitness · Vue guidée — comprendre ce qui a changé, ce qui est vérifié et ce qui demande ton attention

Commencer :
  dw setup                           Relier DiffWitness à Claude/Codex/Cursor pour ce projet Git
  dw status                          Voir les faits connus, inconnus et l’action suivante
Après setup, utilise ton agent de code normalement ; lance `dw status` après une modification.

Quand c’est utile :
  dw explain                         Expliquer la dernière modification à partir des preuves locales, sans IA
  dw protect detect                  Vérifier la protection runtime optionnelle sans modifier la configuration
  dw view technical                  Ouvrir toutes les commandes et détails d’ingénierie

Une action runtime bloquée ou observée ne prouve pas que le logiciel final fonctionne.
DiffWitness vérifie indépendamment la modification Git produite. Sources et prompts/diffs bruts restent locaux par défaut.

Pour toutes les commandes et parcours avancés : `dw view technical`, puis `dw --help`.
"""

TECHNICAL_HELP_FR = """DiffWitness — protéger les actions agent, comprendre, prouver, gérer la dette et préserver la continuité

Commencer :
  dw setup                            Installer l’intégration native Claude/Codex/Cursor pour ce projet Git
  dw setup status                     Vérifier l’intégration installée
  dw status                           Voir Protect, disponibilité des vérifications, modification, dette et actions
  dw protect detect                   Détecter harness/hooks et recommander un mode runtime
  dw protect enable                   Activer la protection intégrée optionnelle
  dw explain                          Afficher l’explication IdleProof déterministe fondée sur les preuves
  dw view guided                      Simplifier la présentation des mêmes faits
  dw doctor                           Contrôler protection, vérifications, dette et continuité

Après setup, utilise Claude Code, Codex ou Cursor normalement. Les frontières restent distinctes :
  PROTECT     protection runtime optionnelle : builtin / external / off ; les observations ne sont pas une Proof
  UNDERSTAND  expliquer les modifications de l’agent dans le projet
  PROVE       exécuter les vérifications sur la modification Git exacte
  OWE         mesurer et conserver les obligations logicielles/de dette
  CONTINUITY  préserver une mémoire bornée pour la prochaine tâche/session/machine

Protect (optionnel) :
  dw protect detect                   Examiner les signaux sans modifier la configuration
  dw protect enable [--policy ...]     Installer les protections PreTool/PostTool Claude/Codex
  dw protect use external             Déléguer la protection live ; conserver Proof/Debt
  dw protect disable                  Retirer les hooks Protect ; conserver Proof/Debt
  dw protect status [--json]           Voir mode, état et reçus bornés
  dw protect log [--json]              Examiner les reçus runtime locaux

La politique Protect est indépendante de la politique Guard. DiffWitness ne force jamais
l’autorisation des actions : les permissions natives du fournisseur restent souveraines.
Le mode off n’installe aucune interception. Codex contrôle fonctionnalité et confiance des hooks ;
DiffWitness installe leur configuration mais n’écrit jamais la confiance Codex. Suis le parcours
Codex, dont `/hooks`, et vérifie dans `dw protect status` qu’un hook live a réellement atteint Protect.

Présentation optionnelle uniquement (les preuves ne changent jamais) :
  dw explain --engine agent-session    Exporter les faits bornés pour le modèle de la session actuelle
  dw explain --engine local            Reformuler avec ton modèle Ollama/OpenAI-compatible local
  dw explain --engine openrouter       Reformuler avec ta clé et tes crédits OpenRouter
  dw explain --engine custom           Reformuler avec ton endpoint compatible

Portal (historique cloud optionnel) :
  dw portal identity [--json]          Voir l’identité locale d’enrôlement projet/machine
  dw portal configure ...              Configurer l’ingestion sans exposer les tokens dans argv
  dw portal status [--json]            Examiner la livraison et la file locale
  dw portal sync [--json]              Envoyer la file de snapshots bornés
  dw portal disconnect                 Retirer la configuration locale des identifiants Portal

Parcours explicites/manuels :
  dw guard [options] -- <agent>         Encadrer un agent/processus par Proof et Debt
  dw gate [options]                     Vérifier un diff Git ou une pull request existante
  dw prove [options]                    Produire les preuves contrefactuelles exhaustives par hunk
  dw debt [options]                     Mesurer et enregistrer la dette d’une modification
  dw health [options]                   Examiner la dette du projet et rapprocher le Debt Ledger
  dw plan [options]                     Préparer un remboursement automatiquement vérifiable
  dw repay [options] -- <agent>         Exécuter une mission bornée et vérifier sa clôture
  dw ledger <action> [options]          Examiner et gérer les obligations durables DW-*

Continuité du projet :
  dw context <task>                     Compiler le contexte borné de la mémoire et de la structure
  dw objective add <text>               Enregistrer un objectif
  dw decision record <text>             Enregistrer une décision, sa justification et ses relations
  dw invariant add <text>               Enregistrer une règle ; --critical la rend toujours pertinente
  dw failed-approach record <text>      Conserver une approche à ne pas répéter
  dw relation add A <type> B            Relier deux faits par une relation typée déclarée humainement
  dw state status                       Examiner le journal append-only et l’état reconstructible
  dw state graph [--entity ID]          Examiner les entités et relations typées
  dw state rebuild                      Reconstruire state.db depuis ProjectEvents et Git
  dw state checkpoint                   Sauvegarder sur refs/diffwitness/project-events
  dw state push                         Pousser sans forcer ni perdre les écritures concurrentes
  dw state pull                         Avancer la mémoire en fast-forward sur une autre machine

Preuves et interopérabilité :
  dw envelope [options]                 Lier Proof, Debt et compréhension à un dwchg_... exact
  dw verify <certificate> [options]     Vérifier l’intégrité et la fraîcheur du certificat
  dw note <certificate> [options]       Référencer une preuve vérifiée dans git notes
  dw core [options]                     Adaptive Core borné et recherche de réduction 1-minimale
  dw recheck <DW-...> [options]         Rejouer la vérification des lignées historiques de dette
  dw ide-hook <event>                   Protocole natif, normalement installé par setup/Protect

La vue est enregistrée dans les métadonnées Git locales du worktree. Guided/Technical changent
uniquement la présentation : Protect, Proof, certificats, Debt Ledger, sources, HEAD, confidentialité
et contrats machine restent identiques. `dw status --view ...` vaut pour une invocation ;
`dw status --json` ne dépend pas de la vue.

Protect, Proof, Debt Ledger, IdleProof déterministe et Continuity fonctionnent localement sans API
modèle ni envoi de sources. Les moteurs de présentation optionnels reçoivent des faits bornés issus
des preuves ; ils appartiennent explicitement à l’utilisateur sauf offre Portal avec Managed AI.
Portal transporte uniquement le contrat produit borné, jamais les prompts/diffs/commandes bruts,
flux d’événements agent ou sources.

`dw status` est une navigation entre observations, preuves, métadonnées Git et obligations, pas une
note de correction. L’intégration native est le parcours principal Claude/Codex ; `dw guard` reste
le recours explicite pour tout agent/processus. Protect intégré cible les hooks Claude/Codex pris en charge.

Utilise `dw <command> --help` pour les options de chaque commande.
"""
