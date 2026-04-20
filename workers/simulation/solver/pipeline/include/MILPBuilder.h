#pragma once
#include "Highs.h"
#include "Config.h"
#include "DataLoader.h"

class MILPBuilder {
public:
    MILPBuilder(const SolverConfig& config, const ProblemData& data);
    HighsModel build();


    struct VarMap {
        std::vector<int> x; // binary species vars
        std::vector<std::vector<int>> v; // species fluxes [species][rxn]
        std::vector<int> v_comm; // community fluxes
        int w_linearization; // aux var
    };
    
    const VarMap& getVars() const { return vars_; }

private:
    SolverConfig config_;
    ProblemData data_;
    HighsModel model_;
    VarMap vars_; 
    
    void addSpeciesVariables();
    void addFluxVariables();
    void addObjectiveLinearizationVariable();
    void addCouplingConstraints();
    void addInternalMassBalance();
    void addCommunityMassBalance();
    void addGrowthConstraint();
    void addFunctionConstraint();
    void addMinSpeciesConstraint();
    void addObjectiveConstraints();
    void addRow(double lb, double ub, const std::vector<int>& idxs, const std::vector<double>& vals);
};
