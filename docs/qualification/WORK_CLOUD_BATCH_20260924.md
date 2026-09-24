# DiffWitness — reprise et lots regroupés, 24 septembre 2026

Mission inachevée : **NOT ALPHA READY**, MACHINE globale incomplète, HUMAN non exécuté.
Le mandat01 et les cinq textes de la session actuelle restent applicables ; les anciens
mandats d'audit ne donnent aucune permission supplémentaire. Registre canonique :
https://github.com/TFourniax/tooltest/issues/74 . Ses dernières entrées priment sur ce snapshot.

Consigne de Thomas appliquée : corrections groupées avant tests, correction locale
des échecs, puis un candidat cohérent en CI. Aucun nouveau push de simple régression
pour fabriquer un BEFORE. Les tests, budgets et garanties restent inchangés.

Cette branche de preuves contient un ancien état de code : ne pas la prendre comme
baseline produit. Reprendre les vrais heads après lecture GitHub. Les anciens worktrees
et index ont été préservés. Le fichier WORK_CLOUD_HANDOFF_20260924.md reste historique.

## Accès et références

Work dispose à nouveau d'un exécuteur : builds, vrais wheel/npm installés et tests ont
été exécutés. Aucun dossier local de Thomas ni fichier d'une autre conversation requis.
Les quatre main ont été relus avant les mutations. Portal a ensuite été fusionné.

| Dépôt | main courant au relevé |
|---|---|
| Core | c03164e75e805ff1df976e55cdf6d86073e89b04 |
| IdleProof | 87a4d8c274edf2b2edcd28bb9ccd34691a5fef14 |
| Portal | a5998dc0a0ad8a8dc62b097890e8b3ba3672751e |
| Private | ce3d2771821b3a9508290311513ce26f98b5c768 |

Portal a été matérialisé par292blobs et modes vérifiés contre son arbre, puis doté
d'un historique local synthétique : ce n'est pas un clone avec historique amont.
Le code Private et les preuves détaillées Portal restent dans leurs dépôts privés.

## Lots réalisés

**Core128 — tranche Q&A citée.**
https://github.com/TFourniax/tooltest/pull/128 . Head publié289ea9020c682ee527c1b44aa42f6a8e7ee7e66f,
tree d1381f4a1971cef81f18a970afa4f3a4488b4ccd. Dates à points sur deux chiffres,
mois abrégés isolés, homographes de fuseaux, interrogatifs dans les noms et questions
composées avec esperluette ont été corrigés par lots. d861ec8 avait24/24jobs PASS
sur35971656258 et trois spécialistes PASS ; ce résultat ne qualifie pas le nouveau head.
Le lot289ea90 passe72tests ciblés,816tests du wheel installé (52skips,90.053s)
et le parcours CLI réel avec citations ouvertes et journal/état inchangés.
Son wheel389172octets a SHA256450734fda5bbf17cfa98f3b15acd769b038d79ab9d5df0a3503816a68bf9a82e.

La dernière revue ajoute les constats52/53 : slash entre questions et ponctuation
interne des noms de dépendances. Corrections locales groupées,72tests ciblés PASS,
816tests installés PASS (52skips,87.471s). Wheel389171octets,
SHA25614677cd60dcf39b6605370bf2ab6c1e88440ac5c497e5410b48b143b29d3f5fd.
Le premier parcours installé a révélé une collision de fixtures («what platform»
et «paths/what platform») : nom changé en «paths/what gateway», assertion exacte
conservée, vérification de non-inclusion des termes de toutes les fixtures, parcours
corrigé encore en cours au snapshot. Pas de merge ni de dernier head qualifié revendiqué.
53constats suivis, corrections anciennes conservées, tous les fils à auditer avant fusion.

**Core129 / PM012 — optimisation sans relâcher la vérité.**
PR diagnostic inchangée26f663b0d2fbecf779324a1f78f8359750787c63.
Code et preuves sauvegardés séparément : branche work/batched-history-20260924,
commit3ff3fc80ff052a4946ee87f4233083946c3c3d6d,tree0117551a1e2dbfd9261581b7bf65f9dd9919157b.
Décodage JSON par lots bornés avec comparaison de chaque ligne à son réencodage
canonique et retour au parseur strict si nécessaire ; toutes les formes, profils,
identités, hashes, chaînes et références ordonnées restent validés. Copie des entrées
détachée avec conservation alias/cycles, dispatch profils, projection SQL groupée et
cache privé borné. Pas de cache persistant faisant confiance à une validation ancienne.
255tests continuité PASS après correction du point d'injection d'un test de course.
Le premier full746tests a échoué sur ce point d'injection ; cet échec est conservé.

100k local après optimisation : append9.497201s<=10 ; verify3.056519s>2 ;
rebuild7.181036s>5 ; cold59.251ms/hotp9562.611ms PASS. **PM012 reste FAIL.**
Pas de nouvelle matrice hébergée sur cette optimisation encore sous les critères.
Profils et logs originaux sont dans docs/qualification/PM_012_HISTORY_100K/work-batch
du commit3ff3fc8. Le profil n'est pas une mesure d'acceptation. Les incidents provider
558.800441ms>500,TypeScript187.065ms>150 et anciens timeouts restent ouverts.

**Portal35 — intégré après qualification du dernier commit.**
https://github.com/TFourniax/idleproof-portal/pull/35 . Candidat552319f6ddf791e57ac7a04233b894945bc242c1,
tree4d70ec9845d29570912fd4b4dec7618472e48656. Navigation des mémoires des reçus
historiques paginés, horloges et sources propres à chaque reçu, relations navigables
si cible unique ; côté absent/ambigu explicite. Les ancres préservent les identités
Unicode, même mal formées, sans crash ni collision. Aucune absence assimilée à suppression,
aucune relation présentée comme causalité expérimentale. Le store normalisé PM013 manque.

Pins Corec03164e / Idle87a4d8c : vrai wheel installé → vrai npm installé → validateur
Portal.369fichiers npm comparés au checkout propre,5citations,4confirmations,identité
longue,libellé banal et confidentialité préservés. Journal/index inchangés.
Wheel Core379103octets SHA256ab66c3112f685ebdb214c81b4a3c10904df85517d3ac240c612a54c6184a5b17 ;
npm813736octets SHA2569fe866d3bfc8ee60c81e03f76522d7ccd031b59145663545d03c00f401ee0009.
Ce sont des archives locales construites et installées, pas des paquets publiés ni
une revendication d'égalité avec les octets des artefacts CI.

352tests locaux et tous les contrôles applicatifs PASS. Revue distincte5810509617
sans nouveau constat. Run35974255497 tentative1 :7/7PASS,head de chaque job vérifié.
Chromium153.0.8010.12 :14/14cas,360/1440px, dont navigation historique,fragment exact,
identités réservées/mal formées,statuts et absence de débordement. Checkout synthétique
a4b1a844a701cc25a043afaba406c63820f46a6a, même tree vérifié par API,parents0e12c644/552319f6.
Trois constats résolus après correction et qualification. Fusion a5998dc0, même tree.
**Main frais encore en attente au snapshot**, pas de résultat PR transféré.

Deux échecs de harness navigateur ont été conservés puis corrigés ensemble avec
les constats de revue. L'installation locale Chromium a échoué (archive téléchargée
invalide) ; aucun navigateur local PASS. Logs locaux privés et manifeste :
https://github.com/TFourniax/idleproof-portal/tree/e7a2108387b2e4e62eec7dac38540c75b4081b4c/docs/qualification/WORK_BATCH_20260924 .

Les dix merges historiques du précédent checkpoint, dont les quatre corrections
A/B (Proof→Debt,chemins capteur,aide CLI,chemins longs), sont préservés. Portal35 est
le onzième merge technique ; aucun parent complet n'est clos par ces seules tranches.

## Tout le périmètre restant

| Parent | Développement / qualification restant |
|---|---|
| PM001 | ABI commune feature/component/symbol et adoption de tous producteurs |
| PM002 | Second-dirty et vrais clients natifs authentifiés |
| PM003 | Parcours all-branch coordonné des produits |
| PM004 | Sémantique riche et incidents provider inter-OS |
| PM005 | Renames modifiés,symboles,split/merge |
| PM006 | Temporalité/lifecycle sur toutes les surfaces |
| PM007 | Dérive sémantique de symboles et dépendances |
| PM008 | Toutes catégories de citations,corpus longitudinal/adverse |
| PM009 | Navigation complète Guided/Portal au-delà des reçus |
| PM010 | Parcours réel HTTP/Edge/DB/auth,natif et candidat coordonné |
| PM011 | Réconciliation multiwriter divergente sans perte |
| PM012 | Budgets100k,monorepos,concurrence,hooks/providers |
| PM013 | Store longitudinal normalisé tenant-safe et sync incrémentale |
| PM014 | Modèle mental causal/temporel complet sur ce store |
| PM015 | Fin Core128 puis Q&A sémantique coordonné Idle/Portal |
| PM016 | Mémoire personnelle viewed/understood/ownership/last-visit séparée |
| PM017 | Effets sémantiques et surfaces Idle/Portal au-delà des plans de fichiers |
| PM018 | Parcours long,candidat figé,toutes gates release,HUMAN réel |

201rattachements de sources restent conservés :72backlog+129exigences. Ce n'est pas
201critères satisfaits. Les restes ci-dessus incluent du développement interne,
pas seulement des autorisations ou accès externes.

## Actions externes réellement nécessaires à la qualification finale

- Clients/comptes de test natifs L1/L2/L3 configurés sur l'infrastructure existante.
  Statut rd-lab inconnu via l'API disponible ; aucune nouvelle machine autorisée.
- Environnement jetable explicitement autorisé pour le parcours Portal HTTP/DB/auth/
  entitlement. La CI replayDB n'est pas cette recette authentifiée globale. Les anciennes
  observations Supabase (0branche,33migrations enregistrées contre38SQL,entitlement absent)
  restent datées et doivent être relues avant toute action. Aucune écriture production.
- Récupération effective des octets d'artefacts CI pour geler la distribution : les
  anciennes tentatives403 et les métadonnées de téléchargement ne sont pas les octets.
- Recette HUMAN nominative sur candidat final figé ; aucun test automatisé ne la remplace.
- Autorisation ciblée de promotion/publication seulement après tous les prérequis.
  #80 reste ouvert ; aucun tag,paquet publié ou déploiement prouvé par ces builds.

Stripe,nouveau runner,dépense supplémentaire,production et publication restent reportés
ou interdits sans autorisation prévue. Ne pas solliciter de secrets dans le chat.

Prochaine action sûre : terminer le parcours installé Core local,publier le lot de
ponctuation une fois qualifié,obtenir revue/CI fraîches ; contrôler le main Portal
fusionné ; poursuivre les fonctions ouvertes et l'optimisation depuis leurs branches.
