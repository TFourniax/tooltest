# DiffWitness — passation Work cloud, 2026-09-24

## État et autorité

**Mission inachevée. NOT ALPHA READY. MACHINE global incomplet ; HUMAN non exécuté.**
Le mandat du fichier01 des cinq pièces jointes de cette session gouverne la mission.
Les archives décrivent leurs anciens mandats et ne donnent aucune autorisation supplémentaire.
Corrections/tests/workflows sans affaiblissement, branches/commits/PR et mise à jour#74 sont autorisés.
Fusion uniquement après qualification du dernier commit ; main frais obligatoire.
Aucune production, publication, dépense supplémentaire ou nouveau runner. Stripe reste reporté.

Registre canonique : https://github.com/TFourniax/tooltest/issues/74
Matrice des18parents : https://github.com/TFourniax/tooltest/issues/74#issuecomment-5805937985
Accès relus : https://github.com/TFourniax/tooltest/issues/74#issuecomment-5807683611
Incident fournisseur frais : https://github.com/TFourniax/tooltest/issues/74#issuecomment-5807926796
Les mises à jour ultérieures de#74/PRs prévalent sur ce snapshot.

Cette branche evidence/pr128-33b1afa-20260924 conserve des preuves ; ce n'est pas la branche produit.
Elle contient un ancien état du code. Reprendre le code sur feat/grounded-memory-questions, après relecture des refs.
L'archive DiffWitness_checkpoint_20260923.zip v5, sauvegardée avant la panne, conserve les cinq textes
et201rattachements de sources, mais son état d'exécution est ancien. Aucun v6 n'est revendiqué.

## Références relues

Les quatre refs main ont encore été relues pendant ce checkpoint ; elles restent inchangées.
L'inventaire courant expose toujours zéro outil d'exécution shell.

| Dépôt | main | Qualification et limite |
|---|---|---|
| TFourniax/tooltest | c03164e75e805ff1df976e55cdf6d86073e89b04 | Fresh main35939990884 :23PASS/1FAIL, TypeScript p95187.065>150ms. Les3spécialistes passent. Pas de MACHINE global. |
| TFourniax/tooltest-2 | 87a4d8c274edf2b2edcd28bb9ccd34691a5fef14 | Fresh main35940622611 :16/16PASS, SHA de chaque job vérifié. Les intermittences antérieures restent ouvertes. |
| TFourniax/idleproof-portal | 0e12c644f1f65f399af76a70ef81a684b5fc64cd | Main inchangé ; preuves source et CI existantes, aucune parité déployée établie. |
| TFourniax/diffwitness-private | ce3d2771821b3a9508290311513ce26f98b5c768 | Qualification historique du même main :5workflows passent ;9jobs Mac automatiques et3authentifiés conditionnels SKIPPED. Pas de L1/L2/L3 authentifié ni HUMAN. |

## Dix PR techniques fusionnées dans cette mission

Les derniers commits ont reçu une revue distincte et leurs gates avant fusion ; les runs main frais
ont ensuite été contrôlés. Les échecs main indiqués restent des échecs, même après une PR verte.

| PR | Changement | Commit de fusion |
|---|---|---|
| Core123 | Aide/version/erreurs CLI avant préflight ou effets | d1222e15989a19f97972164f7d04fe003ef902a7 |
| Core124 | Chemins du capteur Git UTF8/NUL, renames et contrôles | d383b4b3297cd09f057049af8e8db4e4ad164c9e |
| Core125 | Proof→Debt, cinq familles et paire exacte de trees, historique préservé | 8ef8d6322cb1aa73c8c30357c64c2f48bec3aab8 |
| Core126 | sdist installé isolément, inventaire fidèle des tests/ressources | 9c6ce1d38ff2c0a9fcb93c28dd8d2c5dbe101de2 |
| Core127 | Plan immuable et comparaison citée d'impacts de fichiers | c03164e75e805ff1df976e55cdf6d86073e89b04 |
| Idle19 | Verrous EACCES/EPERM/EBUSY avec borne30s | d375177a1a92442eead09f178b37e8957c4824d1 |
| Idle18 | Diagnostics Windows/macOS sans relâcher les gates | 4737555e0699c557b7cca6d1a91768e24a35b704 |
| Idle20 | Chemins longs omis explicitement, compteurs et bornes conservés | f4d585482f5eb5d6e2309ca0bd46ea98930ba10b |
| Idle21 | Archive immuable des observations au-delà de la fenêtre de8 | 76d24a53edd8df127e56d9ff902243c7f6b66a85 |
| Idle22 | Diagnostics bornés des échecs de fournisseur | 87a4d8c274edf2b2edcd28bb9ccd34691a5fef14 |

Les quatre défauts des auditsA/B sont tous conservés : Proof→Debt, chemins capteur,
aide CLI exécutante et chemins longs. Ces dix PR ne ferment aucun des18parents à leur périmètre complet.
Core125 fresh main35933159647 a échoué sur un timeout Windows ; Core127 fresh main échoue sur la latence.
Les diagnostics Idle ne prouvent pas la résolution des incidents antérieurs.

## Candidats actifs — ne pas fusionner sur un ancien PASS

### Core128, tranche extractive de PM015
https://github.com/TFourniax/tooltest/pull/128
Branche feat/grounded-memory-questions.
HEAD **41b0cc55bea6190286ca63c136c3d15779164df4** ; tree **302574b90d5c79293dd417c034d370f670288f0a**.
Base c03164e75e805ff1df976e55cdf6d86073e89b04.
Revue du dernier commit **5300522957**, datée du **2026-09-24 à 06:16:02 UTC**.
**47 constats suivis ; le dernier P1 reste OUVERT et non corrigé** :
https://github.com/TFourniax/tooltest/pull/128#discussion_r4090514176 .
Les dates à points avec une année sur deux chiffres, telles que « 21.09.26 »,
peuvent encore devenir des termes de chemin. La suite actuelle ne couvre pas ce cas.
Aucun nouveau BEFORE/AFTER ni correction n'est revendiqué pour ce47e constat.
Les46 constats précédents ont leurs corrections et régressions ; tous les fils restent audités,
mais une revue avec ce P1 ouvert n'est pas une revue propre.

Dernier BEFORE75add4e /35962880322/job107515376349 : **814 tests, 8 échecs, 52 skips, 82,255 s**.
AFTER du commit41b0cc5, run **35963216955** :
- Ubuntu3.11/job107516369651 : **814 tests, aucun échec, 52 skips, 102,210 s**.
- Parcours CLI installé Ubuntu/job107516369633 : **PASS**, sources ouvertes, octets inchangés,
  sorties MACHINE et human_executed:false.
- Matrice au relevé : **20 success / 4 in_progress** ; tous les24 jobs rattachés au head41b0cc5.
- Proof35963216985, Continuity35963216973 et integrated35963216995 : **PASS**.
- Checkout réel **72fc27c025dc42d915e8f0fcd85b283426943c28**, tree
  **302574b90d5c79293dd417c034d370f670288f0a**, égal au tree du candidat par API ;
  SHA distinct, parents c03164e/41b0cc5.

Logs originaux AFTER et métadonnées de matrice/artefacts conservés dans
**docs/qualification/PR128_41B0CC5_EVIDENCE/** de cette branche de preuves.
Les métadonnées des artefacts ne constituent pas une copie téléchargée de leurs octets.
Le head produit n'est pas déplacé pour conserver ces preuves.

**Non fusionnable : P1 de revue ouvert ET incident fournisseur non résolu.**
Aucun main frais de cette PR, qualification globale, HUMAN ou Alpha n'est revendiqué.

Preuve historique855a850 : **813 tests PASS, 52 skips, 98,670 s**,
job107513900213/run35962389469 ; parcours CLI installé Ubuntu107513900179 PASS.
Checkout réel **8fea59a7b9cf3e57c3fd495bb67d9dfc7989196a**, tree
**4514f90a27cbd416cbc5cb17e414c73533f22237**, identique au head855a850,
vérifié par API ; SHA distinct, parents c03164e/855a850.
Ce run finit à **13 PASS / 11 CANCELLED** après l'ajout de la régression suivante.
Les annulations ne sont pas des PASS. Ces résultats ne qualifient pas41b0cc5.

L'échec installé e7506d1 est préservé. Un nouvel exemple partageait tous ses termes
avec un exemple existant ; correction isolée de cet exemple et assertion exacte
conservée. Le parcours installé bcb85da/107512382213 passe sans changement produit.
Des contrôles supplémentaires démontrent maintenant les deux sources pour des
termes identiques et la sélection exacte par identifiant. Cela n'est pas du Q&A sémantique.

**Incident fournisseur non résolu** : au33b1afa, run35957187387/job107498223040,
hook Python max558.800441ms>500ms, p9579.963834ms<=150. ConsumerIdle2b919f7dddeaf3488091017a46f079d8c9718056,
Node22.23.2/Linux/x64/4CPU. Canonical smoke passe ; les commandes perf TS/data suivantes ne sont
pas exécutées après cet échec. Cause inconnue, pas attribuée arbitrairement au code ou au runner.
Logs intégraux : docs/qualification/PR128_33B1AFA_EVIDENCE/ sur9f4a684ebb5764e66286d83aeb00a1d5acc57972.
Les changements fonctionnels ultérieurs ne corrigent pas ce défaut ; un nouveau vert ne le ferme pas.
Aucun seuil/timeout/garantie n'est affaibli ; aucun retry-to-green demandé.

Le lecteur Q&A reste limité : journal strictement validé, extraction citée, abstention,
aucun modèle/réseau/exécution de question, aucune écriture journal/index, assurance:none.
Il ne termine pas le Q&A sémantique coordonné Idle/Portal ni PM015 complet.

### Core129, diagnostic PM012 DRAFT
https://github.com/TFourniax/tooltest/pull/129
HEAD26f663b0d2fbecf779324a1f78f8359750787c63 ; treeb41b5e554795afb1d419c3fe4127e8b2366c76a2.
Revue propre5805875524 ; test35943403905 :24PASS ; Proof/integrated passent.
**100k FAIL** sur35943403982/job107456031197 :
append10.288582>10s ; verify4.362531>2s ; rebuild9.489516>5s.
Cold69.324ms et hotp9568.248ms passent1000/300ms.
Les profils séparés terminent, journal inchangé ; coûts cumulés se chevauchent et ne sont pas des budgets.
Aucune optimisation produit n'est livrée dans cette PR. Ne pas confondre diagnostic terminé et PM012 résolu.

### Portal35, intégration citée bloquée
https://github.com/TFourniax/idleproof-portal/pull/35
HEADf37436a252bd9fd46f0ba0e7a757915efe0d0a12 ; treef6c286286b313aae2c1da7dc5c78e01b12f02f34.
Revue fraîche propre5806598320. Run35849812537 :**5PASS/2FAIL**, Node22/24.
Le producteur épinglé altère un libellé banal en [redacted] ; l'assertion exacte est conservée.
Les pins et incidents fournisseur ne sont pas qualifiés par le seul dernier vert Idle.
Pas de fusion ni de déploiement.

## Tout le périmètre restant

| Parent | Reste à développer / qualifier |
|---|---|
| PM001 | ABI commune feature/component/symbol, cohérence de tous producteurs |
| PM002 | Second-dirty et parcours natifs authentifiés complets |
| PM003 | Parcours coordonné de toutes les branches et produits |
| PM004 | Sémantique riche et résolution des incidents fournisseur |
| PM005 | Renames modifiés, refactorings symboliques, split/merge, parcours coordonné |
| PM006 | Lecture temporelle complète sur toutes surfaces |
| PM007 | Dépendances/symboles et dérive sémantique complète |
| PM008 | Toutes catégories de citations et corpus longitudinal/adversarial complet |
| PM009 | Guided complet et navigation Portal |
| PM010 | Pins coordonnés, HTTP/DB/auth, natifs, intégration Portal |
| PM011 | Multiwriter divergent sans perte |
| PM012 | Budgets100k et intermittences hooks/fournisseurs |
| PM013 | Stockage longitudinal normalisé Portal, isolation tenant, synchronisation incrémentale |
| PM014 | Carte mentale sur ce stockage et navigation causale/temporelle |
| PM015 | Finaliser/qualifier Core128 puis Q&A sémantique coordonné Idle/Portal |
| PM016 | Mémoire utilisateur viewed/understood/ownership/last-visit séparée des faits projet |
| PM017 | Effets sémantiques complets et surfaces Idle/Portal au-delà des plans de fichiers |
| PM018 | Long parcours authentifié, candidat coordonné, toutes gates release et HUMAN réel |

Ces restes sont du développement et de la qualification, pas uniquement des permissions manquantes.
201rattachements de source ne signifient pas201critères satisfaits.

## Accès et actions externes indispensables

- Rétablir l'exécuteur **Work cloud existant**. Environnement annoncé failed/409environment_offline ;
  aucun outil shell actif au dernier inventaire. GitHub et lectures Supabase restent disponibles.
  Ne pas supposer OOM, survie d'un processus, état d'un profil interrompu ou restauration automatique.
- Rendre disponibles les clients et comptes de test natifs configurés pour L1/L2/L3.
  Le statut actuel du runner rd-lab existant n'est pas lisible via l'endpoint autorisé :
  **inconnu**, pas «offline». Aucun nouveau runner ni dépense n'est autorisé par cette passation.
- Fournir/autoriser le dispositif isolé HTTP/DB/auth/entitlement prévu, sans écrire en production.
  Métadonnées relues : Supabase tebscytrykxfhgduqisk,0branche dev,33migrations enregistrées,
  contre38fichiers SQL du dépôt Portal ; fonctions idleproof-ingest ACTIVEv4 et
  portal-delete-account ACTIVEv1 seulement, pas d'entitlement.
  Absents du registre distant :20260824001000_repository_identity_v3,
  20260829032600_idleproof_managed_inference_guardrails_v1,
  20260829034000_idleproof_global_spend_breaker_v1,
  20260901090000_snapshot_protection_v1,20260911003000_private_engine_entitlement_v1.
  Cela ne prouve ni schéma physique ni SHA applicatif ni parité déployée. Aucune migration appliquée.
- Permettre la récupération des octets des artefacts CI avant gel/qualification de distribution ;
  les téléchargements disponibles ont renvoyé403, les métadonnées seules ne sont pas une copie vérifiée.
- Après développement et MACHINE complète, réaliser une acceptation HUMAN nominative réelle
  sur le candidat gelé : personne, date, scénario, environnement, SHA/artefact.
  Aucun script, test automatisé, acteur de fixture ou ancien PASS ne devient HUMAN.
- Toute promotion/publication attend les prérequis et l'autorisation ciblée du mandat.
  #80, vrai consommateur d'un tag publié, reste ouvert. Aucun déploiement/publication inventé. Stripe reporté.

## Préserver la reprise

Ne pas reset/clean les worktrees existants. Les modifications distantes n'ont pas avancé les HEAD/index locaux.
Après restauration, comparer worktrees/index/stashs aux refs avant toute édition :
core-questions localc031/stage initial363 + stash conservé, très antérieur au head distant ;
core-history-perf cleanc031 avec profil interrompu de résultat inconnu ;
idle-provider-failure, idle-history, core-state-batch et anciens lots sensor/debt/sdist/longpaths
peuvent contenir des stages déjà publiés ou des MERGE_HEAD. Les préserver.

Relire les quatre instructions de dépôt, le fichier01 et toutes les dernières mises à jour#74.
Auditer tous les fils de revue et les SHA effectifs des jobs ; un checkout PR synthétique n'est pas le head.
Résoudre les incidents, terminer les lots indépendants, obtenir revue du dernier commit et toutes gates,
puis seulement fusionner un lot qualifié et vérifier réellement main à son SHA de fusion.
Ne pas réduire les budgets, supprimer une assertion, reclasser un skip ou sélectionner un run vert pour effacer un rouge.
