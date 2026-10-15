Building renovation LCA
=======================

Create the baseline with Core and assign Data constructions. One call to
``building.renovate(windows, insulation)`` is one step; successive calls create
successive steps. Supply annual delivered energy for each reached state.

``assess_renovation`` returns materials this step, materials so far, energy,
total climate impact and savings against the baseline. Each state uses the same
period. Energy impacts from different states are never added together.

The repository README and five notebooks explain the complete worked examples,
Boverket factors, removed quantities and saved-report behavior.

Assessment
----------

.. autofunction:: epsm_lca.assess_renovation

.. autoclass:: epsm_lca.AssessmentSettings
   :members: from_building, summary, to_dict, from_dict

.. autoclass:: epsm_lca.AnnualEnergy
   :members: for_building, summary, to_dict, from_dict

Results
-------

.. autoclass:: epsm_lca.RenovationResult
   :members: baseline, stages, settings, complete, table, summary, quantities, save, load, plot, to_dict, from_dict

.. autoclass:: epsm_lca.StageResult
   :members: complete, summary, quantities, to_dict, from_dict

Existing EPSM integration
-------------------------

.. autofunction:: epsm_lca.assess

.. autoclass:: epsm_lca.LCAResult
   :members: complete, assessment, context_status, contributions, summary, to_dict, from_dict
